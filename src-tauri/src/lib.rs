//! aipotluck-local-client GUI: a thin shell around the upstream CLI.
//!
//! The UI never touches the machine directly. It calls these commands, which either run one of
//! upstream's own entry points with the bundled Python, or proxy an allow-listed request to the
//! upstream service on 127.0.0.1:8069.

mod model_id;
mod pairing;
mod paths;
mod runtime;
mod service;

use runtime::Runtime;
use serde::Serialize;
use serde_json::{json, Value};
use std::process::Child;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_clipboard_manager::ClipboardExt;

const TEST_LLAMA_PORT_ENV: &str = "AIPOTLUCK_GUI_TEST_LLAMA_PORT";

pub const SETTINGS_URL: &str = "https://aipotluck.org/chat/settings/local-inference";

#[derive(Default)]
struct AppState {
    runtime: Mutex<Option<Runtime>>,
    runtime_error: Mutex<Option<String>>,
    /// Only set when this host has no usable OS service manager and the GUI is hosting upstream's
    /// service payload itself (see Runtime::spawn_service).
    hosted_service: Mutex<Option<Child>>,
    busy: Mutex<Option<&'static str>>,
}

#[derive(Serialize, Clone)]
struct TaskLine {
    task: &'static str,
    line: String,
}

#[derive(Serialize, Clone)]
struct TaskDone {
    task: &'static str,
    code: i32,
    ok: bool,
}

fn rt(state: &State<AppState>) -> Result<Runtime, String> {
    if let Some(r) = state.runtime.lock().unwrap().clone() {
        return Ok(r);
    }
    Err(state
        .runtime_error
        .lock()
        .unwrap()
        .clone()
        .unwrap_or_else(|| "the bundled runtime is still unpacking".into()))
}

fn hosted_running(state: &AppState) -> bool {
    let mut guard = state.hosted_service.lock().unwrap();
    match guard.as_mut() {
        Some(child) => match child.try_wait() {
            Ok(None) => true,
            _ => {
                *guard = None;
                false
            }
        },
        None => false,
    }
}

fn stop_hosted(state: &AppState) {
    if let Some(mut child) = state.hosted_service.lock().unwrap().take() {
        // SIGTERM first: upstream's service shuts llama-server and newt down cleanly on it, where
        // a SIGKILL would orphan both.
        #[cfg(unix)]
        {
            let _ = std::process::Command::new("kill")
                .args(["-TERM", &child.id().to_string()])
                .status();
            for _ in 0..50 {
                if let Ok(Some(_)) = child.try_wait() {
                    return;
                }
                std::thread::sleep(std::time::Duration::from_millis(200));
            }
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// When the OS can't keep the service running for us, the GUI does (for as long as it's open).
fn ensure_hosted_service(state: &AppState, rt: &Runtime, probe: &Value) -> Result<bool, String> {
    let installed = probe["installed"].as_bool().unwrap_or(false);
    let usable = probe["service_manager_usable"].as_bool().unwrap_or(true);
    if !installed || usable || hosted_running(state) || service::healthy() {
        return Ok(false);
    }
    let config_dir = probe["layout"]["config_dir"]
        .as_str()
        .ok_or("probe: no config_dir")?;
    let log_dir = probe["layout"]["log_dir"]
        .as_str()
        .ok_or("probe: no log_dir")?;
    let child = rt.spawn_service(config_dir, log_dir)?;
    *state.hosted_service.lock().unwrap() = Some(child);
    for _ in 0..40 {
        if service::healthy() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(250));
    }
    Ok(true)
}

#[tauri::command]
async fn app_state(state: State<'_, AppState>) -> Result<Value, String> {
    let rt = match rt(&state) {
        Ok(r) => r,
        Err(e) => return Ok(json!({ "ready": false, "error": e })),
    };
    let probe = tauri::async_runtime::spawn_blocking({
        let rt = rt.clone();
        move || rt.probe()
    })
    .await
    .map_err(|e| e.to_string())??;
    let started_hosted = ensure_hosted_service(&state, &rt, &probe)?;
    let healthy = tauri::async_runtime::spawn_blocking(service::healthy)
        .await
        .unwrap_or(false);
    Ok(json!({
        "ready": true,
        "probe": probe,
        "service_healthy": healthy,
        "hosted_by_gui": hosted_running(&state),
        "hosted_just_started": started_hosted,
        "upstream_sha": rt.upstream_sha,
        "busy": *state.busy.lock().unwrap(),
        "settings_url": SETTINGS_URL,
    }))
}

fn claim(state: &AppState, task: &'static str) -> Result<(), String> {
    let mut busy = state.busy.lock().unwrap();
    if let Some(other) = *busy {
        return Err(format!("already running: {other}"));
    }
    *busy = Some(task);
    Ok(())
}

fn release(app: &AppHandle) {
    *app.state::<AppState>().busy.lock().unwrap() = None;
}

/// Run an upstream module in the background, streaming its output to the UI as `task-log` events
/// and finishing with one `task-done` event.
fn spawn_task(
    app: AppHandle,
    task: &'static str,
    module: &'static str,
    args: Vec<String>,
    after: impl FnOnce(&AppHandle, i32) + Send + 'static,
) -> Result<(), String> {
    let state = app.state::<AppState>();
    let rt = rt(&state)?;
    claim(&state, task)?;
    std::thread::spawn(move || {
        let emit_app = app.clone();
        let code = rt
            .run_module_streaming(module, &args, move |line| {
                let _ = emit_app.emit(
                    "task-log",
                    TaskLine {
                        task,
                        line: line.to_string(),
                    },
                );
            })
            .unwrap_or_else(|e| {
                let _ = app.emit("task-log", TaskLine { task, line: e });
                -1
            });
        after(&app, code);
        release(&app);
        let _ = app.emit(
            "task-done",
            TaskDone {
                task,
                code,
                ok: code == 0,
            },
        );
    });
    Ok(())
}

/// `None` for upstream's default model; otherwise the id typed into Customize, refused unless it is
/// a well-formed `owner/repo[:quant]` (see model_id.rs).
fn checked_model(model_hf: Option<String>) -> Result<Option<String>, String> {
    match model_hf.as_deref().map(str::trim) {
        None | Some("") => Ok(None),
        Some(raw) => model_id::parse(raw).map(Some).ok_or_else(|| {
            format!("“{raw}” isn’t a Hugging Face model id. Use owner/repo, or owner/repo:QUANT.")
        }),
    }
}

/// The compute picker's choices (Customize, Linux and Windows): `None` is auto-detect, which is
/// what upstream's installer does by default. Anything else is refused before it reaches a
/// command line.
const PICKER_BACKENDS: [&str; 3] = ["cuda", "vulkan", "cpu"];

fn checked_backend(backend: Option<String>) -> Result<Option<String>, String> {
    match backend.as_deref().map(str::trim) {
        None | Some("") | Some("auto") => Ok(None),
        Some(b) if PICKER_BACKENDS.contains(&b) => Ok(Some(b.to_string())),
        Some(b) => Err(format!("“{b}” isn’t a compute option. Use CUDA, Vulkan or CPU.")),
    }
}

/// What Set up would install, with approximate sizes: the client as unpacked on disk, then
/// upstream's own choice of llama.cpp build (for the auto-detected backend, or the one chosen in
/// Customize), newt binary and model (sidecar/gui_plan.py), plus the compute picker's options.
#[tauri::command]
async fn install_plan(
    state: State<'_, AppState>,
    model_hf: Option<String>,
    backend: Option<String>,
) -> Result<Value, String> {
    let model = checked_model(model_hf)?;
    let backend = checked_backend(backend)?;
    let rt = rt(&state)?;
    tauri::async_runtime::spawn_blocking(move || {
        let mut plan = rt.plan(model.as_deref(), backend.as_deref(), false)?;
        plan["client"] = json!({ "bytes": rt.client_bytes(), "upstream_sha": rt.upstream_sha });
        Ok(plan)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// How big a model's download is, by upstream's own reckoning (model_preflight), for the progress
/// shown while Add downloads it. `null` bytes when Hugging Face can't say.
#[tauri::command]
async fn model_size(state: State<'_, AppState>, model_hf: String) -> Result<Value, String> {
    let model = checked_model(Some(model_hf))?.ok_or("no model given")?;
    let rt = rt(&state)?;
    tauri::async_runtime::spawn_blocking(move || Ok(rt.plan(Some(&model), None, true)?["model"].take()))
        .await
        .map_err(|e| e.to_string())?
}

/// One click: upstream's installer with its defaults (auto-detected backend, default model
/// pre-fetched and sized), or with the model and compute backend chosen in Customize. On a host with no usable service
/// manager it installs without starting the OS service, and the GUI hosts upstream's service
/// payload instead.
#[tauri::command]
async fn setup_device(
    app: AppHandle,
    state: State<'_, AppState>,
    model_hf: Option<String>,
    backend: Option<String>,
) -> Result<(), String> {
    let model = checked_model(model_hf)?;
    let backend = checked_backend(backend)?;
    let rt = rt(&state)?;
    let probe = tauri::async_runtime::spawn_blocking(move || rt.probe())
        .await
        .map_err(|e| e.to_string())??;
    let mut args = vec![format!("--backend={}", backend.as_deref().unwrap_or("auto"))];
    if let Some(m) = model {
        // One token, so the value can never be read as a flag of its own.
        args.push(format!("--model-hf={m}"));
    }
    // Test-only, alongside service::TEST_PORT_ENV: keep llama-server off a real install's port.
    if let Some(port) = std::env::var(TEST_LLAMA_PORT_ENV)
        .ok()
        .and_then(|p| p.parse::<u16>().ok())
    {
        args.push(format!("--server-port={port}"));
    }
    if !probe["service_manager_usable"].as_bool().unwrap_or(true) {
        args.push("--no-start".into());
    }
    spawn_task(
        app,
        "setup",
        "aipotluck.installer.install",
        args,
        |app, code| {
            if code == 0 {
                restart_hosted_if_needed(app);
            }
        },
    )
}

fn restart_hosted_if_needed(app: &AppHandle) {
    let state = app.state::<AppState>();
    let Ok(rt) = rt(&state) else { return };
    let Ok(probe) = rt.probe() else { return };
    if probe["service_manager_usable"].as_bool().unwrap_or(true) {
        return;
    }
    stop_hosted(&state);
    if let Err(e) = ensure_hosted_service(&state, &rt, &probe) {
        let _ = app.emit(
            "task-log",
            TaskLine {
                task: "service",
                line: e,
            },
        );
    }
}

/// What's on the clipboard, if (and only if) it's an aipotluck.org pairing. Never the secret.
#[tauri::command]
fn clipboard_pairing(app: AppHandle) -> Option<pairing::PairingPreview> {
    let text = app.clipboard().read_text().ok()?;
    pairing::recognise(&text)
}

/// Pair with the JSON from aipotluck.org -- `pasted` if the user pasted it, otherwise whatever is
/// on the clipboard. Hands it to upstream's `cli login --credentials-file`, through a 0600 file
/// that is removed as soon as login exits.
#[tauri::command]
fn pair(app: AppHandle, pasted: Option<String>) -> Result<(), String> {
    let raw = match pasted {
        Some(p) => p,
        None => app
            .clipboard()
            .read_text()
            .map_err(|e| format!("clipboard: {e}"))?,
    };
    if pairing::recognise(&raw).is_none() {
        return Err("That isn't the pairing code from aipotluck.org.".into());
    }
    let creds = runtime::write_private_credentials(&raw)?;
    let args = vec![
        "login".into(),
        "--credentials-file".into(),
        creds.to_string_lossy().into_owned(),
    ];
    let creds_for_cleanup = creds.clone();
    spawn_task(
        app,
        "pair",
        "aipotluck.installer.cli",
        args,
        move |app, code| {
            let _ = std::fs::remove_file(&creds_for_cleanup);
            if code == 0 {
                // Don't leave the secret sitting on the clipboard once it has done its job.
                if let Ok(t) = app.clipboard().read_text() {
                    if pairing::recognise(&t).is_some() {
                        let _ = app.clipboard().write_text(String::new());
                    }
                }
                restart_hosted_if_needed(app);
            }
        },
    )
    .inspect_err(|_| {
        let _ = std::fs::remove_file(&creds);
    })
}

#[tauri::command]
fn unpair(app: AppHandle) -> Result<(), String> {
    spawn_task(
        app,
        "unpair",
        "aipotluck.installer.cli",
        vec!["logout".into()],
        |app, code| {
            if code == 0 {
                restart_hosted_if_needed(app);
            }
        },
    )
}

#[tauri::command]
async fn service_call(
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<service::ServiceResponse, String> {
    tauri::async_runtime::spawn_blocking(move || service::call(&method, &path, body))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
fn open_settings_page() -> Result<(), String> {
    open_url(SETTINGS_URL)
}

fn open_url(url: &str) -> Result<(), String> {
    let (cmd, args): (&str, Vec<&str>) = if cfg!(target_os = "macos") {
        ("open", vec![url])
    } else if cfg!(windows) {
        ("cmd", vec!["/C", "start", "", url])
    } else {
        ("xdg-open", vec![url])
    };
    std::process::Command::new(cmd)
        .args(args)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("couldn't open a browser ({e}); visit {url}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_clipboard_manager::init())
        .manage(AppState::default())
        .setup(|app| {
            let handle = app.handle().clone();
            let resource_dir = app.path().resource_dir()?;
            std::thread::spawn(move || {
                let state = handle.state::<AppState>();
                match runtime::ensure_unpacked(&resource_dir) {
                    Ok(r) => *state.runtime.lock().unwrap() = Some(r),
                    Err(e) => *state.runtime_error.lock().unwrap() = Some(e),
                }
                let _ = handle.emit("runtime-ready", ());
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            app_state,
            install_plan,
            model_size,
            setup_device,
            clipboard_pairing,
            pair,
            unpair,
            service_call,
            open_settings_page
        ])
        .build(tauri::generate_context!())
        .expect("error while building the app")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                stop_hosted(&app.state::<AppState>());
            }
        });
}

#[cfg(test)]
mod tests {
    use super::checked_backend;

    #[test]
    fn the_compute_picker_accepts_only_its_three_choices_or_auto() {
        assert_eq!(checked_backend(None), Ok(None));
        assert_eq!(checked_backend(Some("auto".into())), Ok(None));
        assert_eq!(checked_backend(Some(" ".into())), Ok(None));
        for b in ["cuda", "vulkan", "cpu"] {
            assert_eq!(checked_backend(Some(b.into())), Ok(Some(b.into())));
        }
        // Never reaches the installer's command line: not a choice, or an attempt at a flag.
        for bad in ["rocm", "metal", "CUDA", "--no-service", "cpu --system"] {
            assert!(checked_backend(Some(bad.into())).is_err(), "{bad}");
        }
    }
}
