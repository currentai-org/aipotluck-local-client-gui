//! Bundled runtime: unpack once, then run upstream's own entry points with it.
//!
//! Every action the GUI takes on the machine is one of upstream's commands, run exactly as a
//! terminal user would run it -- `python -m aipotluck.installer.install ...`,
//! `python -m aipotluck.installer.cli login --credentials-file ...` -- so the llama.cpp / newt
//! binaries, their pins and checksums, runtime.json and the OS service registration are all
//! upstream's, never a second implementation.

use crate::paths;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};

/// `resources/runtime/manifest.json`, written by `tools/stage-runtime.sh`.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RuntimeManifest {
    pub python_tag: String,
    pub python_archive: String,
    pub python_sha256: String,
    pub upstream_sha: String,
    pub upstream_archive: String,
    pub upstream_sha256: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct Runtime {
    pub python: PathBuf,
    /// The unpacked interpreter's root (what `python` lives inside).
    pub python_dir: PathBuf,
    pub upstream: PathBuf,
    pub probe_script: PathBuf,
    pub plan_script: PathBuf,
    pub server_script: PathBuf,
    pub upstream_sha: String,
}

const READY_MARKER: &str = ".unpacked-ok";

fn sha256_file(path: &Path) -> Result<String, String> {
    use sha2::{Digest, Sha256};
    let mut f = fs::File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
    let mut h = Sha256::new();
    let mut buf = [0u8; 64 * 1024];
    loop {
        let n = f.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(h.finalize().iter().map(|b| format!("{b:02x}")).collect())
}

/// Unpack `archive` into `dest` (atomically: into a sibling temp dir, then rename), verifying the
/// archive's sha256 first. A dir that already carries the ready-marker is reused as-is.
fn unpack_verified(archive: &Path, expected_sha: &str, dest: &Path) -> Result<(), String> {
    if dest.join(READY_MARKER).exists() {
        return Ok(());
    }
    let actual = sha256_file(archive)?;
    if actual != expected_sha {
        return Err(format!(
            "bundled archive {} is corrupt (sha256 {actual}, expected {expected_sha})",
            archive.display()
        ));
    }
    let parent = dest.parent().ok_or("bad destination")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let tmp = parent.join(format!(
        ".{}.partial-{}",
        dest.file_name().unwrap().to_string_lossy(),
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp).map_err(|e| e.to_string())?;
    let f = fs::File::open(archive).map_err(|e| e.to_string())?;
    let mut ar = tar::Archive::new(flate2::read::GzDecoder::new(f));
    ar.set_preserve_permissions(true);
    ar.unpack(&tmp)
        .map_err(|e| format!("unpack {}: {e}", archive.display()))?;
    fs::write(tmp.join(READY_MARKER), expected_sha).map_err(|e| e.to_string())?;
    let _ = fs::remove_dir_all(dest);
    fs::rename(&tmp, dest).map_err(|e| format!("rename into {}: {e}", dest.display()))?;
    Ok(())
}

/// Our own read-only scripts are not upstream's: keep them beside, never inside, the upstream tree.
fn install_sidecar(rdir: &Path, root: &Path, name: &str) -> Result<PathBuf, String> {
    let dest = root.join(name);
    let fresh = fs::read(rdir.join(name)).map_err(|e| format!("bundled {name} missing: {e}"))?;
    if fs::read(&dest).ok().as_deref() != Some(&fresh[..]) {
        fs::write(&dest, &fresh).map_err(|e| e.to_string())?;
    }
    Ok(dest)
}

/// Bytes on disk under `path`, following no symlinks. Unreadable entries count as zero.
fn dir_bytes(path: &Path) -> u64 {
    let Ok(meta) = fs::symlink_metadata(path) else {
        return 0;
    };
    if !meta.is_dir() {
        return meta.len();
    }
    fs::read_dir(path)
        .map(|entries| entries.flatten().map(|e| dir_bytes(&e.path())).sum())
        .unwrap_or(0)
}

pub fn ensure_unpacked(resource_dir: &Path) -> Result<Runtime, String> {
    let rdir = resource_dir.join("runtime");
    let manifest_path = rdir.join("manifest.json");
    let manifest: RuntimeManifest =
        serde_json::from_slice(&fs::read(&manifest_path).map_err(|e| {
            format!(
                "bundled runtime missing ({}): {e} -- run tools/stage-runtime.sh",
                manifest_path.display()
            )
        })?)
        .map_err(|e| format!("bad runtime manifest: {e}"))?;

    let root = paths::runtime_root();
    let py_dir = paths::python_dir(&root, &manifest.python_tag);
    unpack_verified(
        &rdir.join(&manifest.python_archive),
        &manifest.python_sha256,
        &py_dir,
    )?;
    let up_dir = paths::upstream_dir(&root, &manifest.upstream_sha);
    unpack_verified(
        &rdir.join(&manifest.upstream_archive),
        &manifest.upstream_sha256,
        &up_dir,
    )?;

    let probe_script = install_sidecar(&rdir, &root, "gui_probe.py")?;
    let plan_script = install_sidecar(&rdir, &root, "gui_plan.py")?;
    let server_script = install_sidecar(&rdir, &root, "gui_server.py")?;

    let python = paths::python_exe(&py_dir);
    if !python.exists() {
        return Err(format!("bundled python not found at {}", python.display()));
    }
    Ok(Runtime {
        python,
        python_dir: py_dir,
        upstream: up_dir,
        probe_script,
        plan_script,
        server_script,
        upstream_sha: manifest.upstream_sha,
    })
}

impl Runtime {
    /// A Command running the bundled interpreter with upstream's checkout as cwd, unbuffered, and
    /// with nothing inherited that could make it pick up a different Python's packages.
    pub fn python_cmd(&self) -> Command {
        let mut c = Command::new(&self.python);
        c.current_dir(&self.upstream)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONNOUSERSITE", "1")
            .env_remove("PYTHONPATH")
            .env_remove("PYTHONHOME")
            .stdin(Stdio::null());
        // A GUI-subsystem app on Windows spawning a console program (python.exe) pops a console
        // window per child unless told not to -- one flashing black window per probe, every
        // poll. CREATE_NO_WINDOW suppresses it.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            c.creation_flags(CREATE_NO_WINDOW);
        }
        c
    }

    pub fn probe(&self) -> Result<serde_json::Value, String> {
        let out = self
            .python_cmd()
            .arg(&self.probe_script)
            .output()
            .map_err(|e| format!("probe failed to start: {e}"))?;
        if !out.status.success() {
            return Err(format!(
                "probe failed: {}",
                String::from_utf8_lossy(&out.stderr)
            ));
        }
        serde_json::from_slice(&out.stdout).map_err(|e| format!("probe output: {e}"))
    }

    /// What Set up would install and how big each part is (sidecar/gui_plan.py). Reads only; asks
    /// Hugging Face and GitHub for sizes, so it can take a few seconds.
    pub fn plan(
        &self,
        model_hf: Option<&str>,
        model_only: bool,
    ) -> Result<serde_json::Value, String> {
        let mut cmd = self.python_cmd();
        cmd.arg(&self.plan_script);
        if let Some(m) = model_hf {
            cmd.arg(format!("--model-hf={m}"));
        }
        if model_only {
            cmd.arg("--model-only");
        }
        let out = cmd
            .output()
            .map_err(|e| format!("plan failed to start: {e}"))?;
        if !out.status.success() {
            return Err(format!(
                "plan failed: {}",
                String::from_utf8_lossy(&out.stderr)
            ));
        }
        serde_json::from_slice(&out.stdout).map_err(|e| format!("plan output: {e}"))
    }

    /// Which AI Potluck server one-click pairing would use, given the GUI's saved override (if any),
    /// as upstream's own pairing.resolve_server_url() decides it (sidecar/gui_server.py).
    pub fn server(&self, server_url: Option<&str>) -> Result<serde_json::Value, String> {
        let mut cmd = self.python_cmd();
        cmd.arg(&self.server_script);
        if let Some(u) = server_url {
            // One token, so the value can never be read as a flag of its own.
            cmd.arg(format!("--server-url={u}"));
        }
        let out = cmd
            .output()
            .map_err(|e| format!("server lookup failed to start: {e}"))?;
        if !out.status.success() {
            return Err(format!(
                "server lookup failed: {}",
                String::from_utf8_lossy(&out.stderr)
            ));
        }
        serde_json::from_slice(&out.stdout).map_err(|e| format!("server lookup output: {e}"))
    }

    /// The client as installed: the bundled interpreter plus upstream's source, as unpacked.
    pub fn client_bytes(&self) -> u64 {
        dir_bytes(&self.python_dir) + dir_bytes(&self.upstream)
    }

    /// Run an upstream module to completion, calling `on_line` for each output line (stdout and
    /// stderr merged in arrival order per stream). Returns the exit code.
    pub fn run_module_streaming(
        &self,
        module: &str,
        args: &[String],
        on_spawn: impl FnOnce(u32),
        on_line: impl Fn(&str) + Send + Sync + 'static,
    ) -> Result<i32, String> {
        let mut child = self
            .python_cmd()
            .arg("-m")
            .arg(module)
            .args(args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("could not start {module}: {e}"))?;
        on_spawn(child.id());
        let on_line = std::sync::Arc::new(on_line);
        let mut threads = vec![];
        for stream in [
            child
                .stdout
                .take()
                .map(|s| Box::new(s) as Box<dyn Read + Send>),
            child
                .stderr
                .take()
                .map(|s| Box::new(s) as Box<dyn Read + Send>),
        ]
        .into_iter()
        .flatten()
        {
            let cb = on_line.clone();
            threads.push(std::thread::spawn(move || {
                for line in BufReader::new(stream).lines().map_while(Result::ok) {
                    cb(&line);
                }
            }));
        }
        let status = child.wait().map_err(|e| e.to_string())?;
        for t in threads {
            let _ = t.join();
        }
        Ok(status.code().unwrap_or(-1))
    }

    /// Spawn upstream's service payload directly -- the exact argv the systemd unit's ExecStart
    /// carries -- for hosts with no usable service manager (containers, WSL without systemd).
    /// Lives only as long as the GUI.
    pub fn spawn_service(&self, config_dir: &str, log_dir: &str) -> Result<Child, String> {
        fs::create_dir_all(log_dir).map_err(|e| e.to_string())?;
        let log = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(Path::new(log_dir).join("aipotluck.gui-hosted.log"))
            .map_err(|e| e.to_string())?;
        let log2 = log.try_clone().map_err(|e| e.to_string())?;
        let mut cmd = self.python_cmd();
        cmd.arg(
            self.upstream
                .join("aipotluck")
                .join("service")
                .join("aipotluck_service.py"),
        )
        .args(["--config-dir", config_dir, "--log-dir", log_dir]);
        if let Some(port) = crate::service::test_port() {
            cmd.args(["--port", &port.to_string()]);
        }
        cmd.stdout(log).stderr(log2);
        // A GUI-hosted service must never outlive the GUI, even when the GUI dies without running
        // its exit handler (killed, crashed, session torn down). On Linux the kernel enforces that:
        // SIGTERM the child the moment its parent dies -- which upstream's service handles by
        // stopping llama-server and newt cleanly. Found by tools/e2e-smoke.py: a WebDriver session
        // teardown killed the app and left the service orphaned.
        //
        // "Parent" here is the *thread* that forked, not the process, so the spawn itself happens
        // on the spawner thread (on_spawner_thread), which lives as long as the app. Spawned from
        // a Tauri worker thread instead, the service was SIGTERMed whenever that thread retired:
        // its own log showed it stopping 45ms after starting newt, and a stop racing newt's start
        // orphaned newt -- a tunnel left open with no service behind it.
        #[cfg(target_os = "linux")]
        unsafe {
            use std::os::unix::process::CommandExt;
            cmd.pre_exec(|| {
                if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        on_spawner_thread(move || cmd.spawn())
            .map_err(|e| format!("could not start the service: {e}"))
    }
}

type SpawnJob = Box<dyn FnOnce() + Send>;

/// Run `f` on the one thread that starts hosted services, and wait for its result. That thread
/// is never joined and never exits before the process does (see spawn_service for why).
fn on_spawner_thread<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> T {
    use std::sync::{mpsc, Mutex, OnceLock};
    static SPAWNER: OnceLock<Mutex<mpsc::Sender<SpawnJob>>> = OnceLock::new();
    let spawner = SPAWNER.get_or_init(|| {
        let (tx, rx) = mpsc::channel::<SpawnJob>();
        std::thread::Builder::new()
            .name("hosted-service-spawner".into())
            .spawn(move || {
                for job in rx {
                    job();
                }
            })
            .expect("could not start the hosted-service spawner thread");
        Mutex::new(tx)
    });
    let (done_tx, done_rx) = mpsc::channel();
    spawner
        .lock()
        .unwrap()
        .send(Box::new(move || {
            let _ = done_tx.send(f());
        }))
        .expect("hosted-service spawner thread is gone");
    done_rx
        .recv()
        .expect("hosted-service spawner thread is gone")
}

/// Write the pairing JSON to a private temp file (0600, inside our own runtime dir), for
/// `cli login --credentials-file`. The secret never goes on argv, where `ps` would show it.
pub fn write_private_credentials(raw: &str) -> Result<PathBuf, String> {
    let dir = paths::runtime_root();
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join(format!(".pairing-{}.json", std::process::id()));
    let _ = fs::remove_file(&path);
    let mut opts = fs::OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    let mut f = opts.open(&path).map_err(|e| e.to_string())?;
    use std::io::Write;
    f.write_all(raw.trim().as_bytes())
        .map_err(|e| e.to_string())?;
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::on_spawner_thread;

    /// What the kernel ties PR_SET_PDEATHSIG to is the forking thread, so every call must land on
    /// the same long-lived thread -- whichever short-lived thread asked.
    #[test]
    fn hosted_services_are_always_started_from_one_thread_that_outlives_the_caller() {
        let ids: Vec<_> = (0..4)
            .map(|_| {
                std::thread::spawn(|| on_spawner_thread(|| std::thread::current().id()))
                    .join()
                    .unwrap()
            })
            .collect();
        assert!(
            ids.windows(2).all(|w| w[0] == w[1]),
            "spawns landed on different threads: {ids:?}"
        );
        assert_ne!(ids[0], std::thread::current().id());
    }
}
