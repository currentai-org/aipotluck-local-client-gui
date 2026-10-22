//! Uninstall: the part the GUI removes itself, after upstream's own `cli uninstall` has stopped and
//! removed the service and deleted the CLI's install (llama.cpp, newt, config, logs, downloads).
//!
//! What's left is the GUI's own:
//! - the bundled runtime unpacked into `<data_home>/aipotluck/gui-runtime` (only when the CLI goes
//!   too -- a kept CLI's service runs from that interpreter and source);
//! - the webview's data and caches, in the per-app directories Tauri derives from the identifier;
//! - the app itself: run its NSIS uninstaller on Windows, delete the `.app` on macOS, delete the
//!   AppImage on Linux. A `.deb` install belongs to the package manager and is left for it.
//!
//! Most of that is in use while the app runs (its own executable, the webview's profile), so it is
//! handed to a small detached process that waits for this one to exit and then deletes it.

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// How this copy of the app was installed, which decides how it removes itself.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AppInstall {
    /// Windows NSIS install: its own uninstaller sits beside the executable.
    WindowsNsis { uninstaller: PathBuf },
    /// A macOS `.app` bundle.
    MacApp { bundle: PathBuf },
    /// A Linux AppImage (the `APPIMAGE` variable names the file).
    AppImage { file: PathBuf },
    /// Installed by a system package manager (a `.deb` under /usr): not ours to delete.
    SystemPackage { binary: PathBuf },
    /// Anything else -- a development build. Left alone.
    Unmanaged { binary: PathBuf },
}

impl AppInstall {
    pub fn detect(exe: &Path, appimage: Option<PathBuf>) -> AppInstall {
        let binary = exe.to_path_buf();
        if cfg!(windows) {
            if let Some(dir) = exe.parent() {
                let uninstaller = dir.join("uninstall.exe");
                if uninstaller.exists() {
                    return AppInstall::WindowsNsis { uninstaller };
                }
            }
            return AppInstall::Unmanaged { binary };
        }
        if cfg!(target_os = "macos") {
            // <bundle>.app/Contents/MacOS/<binary>
            let bundle = exe.ancestors().nth(3).map(Path::to_path_buf);
            if let Some(bundle) = bundle {
                let is_app = bundle.extension().is_some_and(|e| e == "app");
                let in_build_tree = bundle.components().any(|c| c.as_os_str() == "target");
                if is_app && !in_build_tree {
                    return AppInstall::MacApp { bundle };
                }
            }
            return AppInstall::Unmanaged { binary };
        }
        if let Some(file) = appimage.filter(|f| f.is_file()) {
            return AppInstall::AppImage { file };
        }
        // The .deb installs to /usr/bin. Not /opt: that's also where people keep checkouts (this
        // repo's own dev host does), and a dev build was misreported as a package install.
        if exe.starts_with("/usr") {
            return AppInstall::SystemPackage { binary };
        }
        AppInstall::Unmanaged { binary }
    }

    pub fn kind(&self) -> &'static str {
        match self {
            AppInstall::WindowsNsis { .. } => "windows-nsis",
            AppInstall::MacApp { .. } => "macos-app",
            AppInstall::AppImage { .. } => "appimage",
            AppInstall::SystemPackage { .. } => "system-package",
            AppInstall::Unmanaged { .. } => "unmanaged",
        }
    }

    /// What the dialog should say about the app itself, if it won't simply disappear.
    pub fn note(&self) -> Option<String> {
        match self {
            AppInstall::SystemPackage { .. } => Some(
                "The app itself was installed by your system's package manager. Remove it afterwards \
                 with: sudo apt remove aipotluck-local-client-gui"
                    .into(),
            ),
            AppInstall::Unmanaged { binary } => Some(format!(
                "This copy of the app ({}) isn't an installed one, so it stays.",
                binary.display()
            )),
            _ => None,
        }
    }

    /// The file or bundle to delete directly (Windows uses its uninstaller instead).
    fn deletable(&self) -> Option<&Path> {
        match self {
            AppInstall::MacApp { bundle } => Some(bundle),
            AppInstall::AppImage { file } => Some(file),
            _ => None,
        }
    }
}

/// Refuses anything that could be more than this app's own files: a filesystem root, the home
/// directory or one of its parents, or a path that isn't recognisably ours (named for the app's
/// identifier, the bundled runtime, or the app artifact itself).
pub fn safe_to_delete(path: &Path, home: &Path, identifier: &str, app: &AppInstall) -> bool {
    if path.parent().is_none() || path == home || home.starts_with(path) {
        return false;
    }
    if app.deletable() == Some(path) {
        return true;
    }
    let ours = |c: &std::ffi::OsStr| c == identifier || c == "gui-runtime";
    path.components().any(|c| ours(c.as_os_str()))
}

/// What the cleanup process will delete, filtered by `safe_to_delete`.
pub fn plan(
    candidates: Vec<PathBuf>,
    home: &Path,
    identifier: &str,
    app: &AppInstall,
) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = vec![];
    let all = candidates
        .into_iter()
        .chain(app.deletable().map(Path::to_path_buf));
    for p in all {
        if safe_to_delete(&p, home, identifier, app) && !out.contains(&p) {
            out.push(p);
        }
    }
    out
}

fn ps_quote(p: &Path) -> String {
    format!("'{}'", p.display().to_string().replace('\'', "''"))
}

/// A detached process that waits for `pid` to exit, runs the Windows uninstaller if there is one,
/// then deletes `paths`.
pub fn cleanup_command(pid: u32, app: &AppInstall, paths: &[PathBuf]) -> Command {
    if cfg!(windows) {
        let mut script = format!(
            "$ErrorActionPreference='SilentlyContinue'; Wait-Process -Id {pid} -Timeout 120; Start-Sleep -Milliseconds 500; "
        );
        if let AppInstall::WindowsNsis { uninstaller } = app {
            script += &format!(
                "Start-Process -FilePath {} -ArgumentList '/S' -Wait; Start-Sleep -Seconds 2; ",
                ps_quote(uninstaller)
            );
        }
        for p in paths {
            script += &format!("Remove-Item -LiteralPath {} -Recurse -Force; ", ps_quote(p));
        }
        let mut c = Command::new("powershell.exe");
        c.args([
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            &script,
        ]);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
            c.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP);
        }
        c.stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        return c;
    }
    let mut c = Command::new("/bin/sh");
    c.arg("-c")
        .arg(
            "pid=$1; shift; i=0; while kill -0 \"$pid\" 2>/dev/null && [ $i -lt 600 ]; do \
             sleep 0.2; i=$((i+1)); done; rm -rf -- \"$@\"",
        )
        .arg("aipotluck-uninstall")
        .arg(pid.to_string())
        .args(paths);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        c.process_group(0); // not in the app's group, so nothing that ends the app ends this
    }
    c.stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    c
}

#[cfg(test)]
mod tests {
    use super::*;

    const ID: &str = "org.aipotluck.localclient";

    fn dev() -> AppInstall {
        AppInstall::Unmanaged {
            binary: "/src/target/debug/app".into(),
        }
    }

    #[test]
    fn never_deletes_a_root_the_home_dir_or_one_of_its_parents() {
        let home = Path::new("/home/u");
        for p in ["/", "/home", "/home/u"] {
            assert!(!safe_to_delete(Path::new(p), home, ID, &dev()), "{p}");
        }
        // Even when the name check alone would let it through: a home directory (or a parent of
        // it) that happens to be named like one of ours is still never deleted.
        let odd_home = Path::new("/srv/gui-runtime/u");
        for p in ["/srv/gui-runtime", "/srv/gui-runtime/u"] {
            assert!(!safe_to_delete(Path::new(p), odd_home, ID, &dev()), "{p}");
        }
    }

    #[test]
    fn deletes_only_paths_recognisably_ours() {
        let home = Path::new("/home/u");
        assert!(safe_to_delete(
            Path::new("/home/u/.local/share/org.aipotluck.localclient"),
            home,
            ID,
            &dev()
        ));
        assert!(safe_to_delete(
            Path::new("/home/u/.local/share/aipotluck/gui-runtime"),
            home,
            ID,
            &dev()
        ));
        // the CLI's install is upstream's to delete, never ours
        assert!(!safe_to_delete(
            Path::new("/home/u/.local/share/aipotluck"),
            home,
            ID,
            &dev()
        ));
        assert!(!safe_to_delete(
            Path::new("/home/u/.cache/huggingface"),
            home,
            ID,
            &dev()
        ));
        assert!(!safe_to_delete(
            Path::new("/home/u/Downloads"),
            home,
            ID,
            &dev()
        ));
    }

    #[test]
    fn the_app_artifact_itself_is_deletable_whatever_its_name() {
        let home = Path::new("/home/u");
        let app = AppInstall::AppImage {
            file: "/home/u/Apps/AI-Potluck.AppImage".into(),
        };
        let planned = plan(
            vec!["/home/u/.cache/org.aipotluck.localclient".into()],
            home,
            ID,
            &app,
        );
        assert_eq!(
            planned,
            vec![
                PathBuf::from("/home/u/.cache/org.aipotluck.localclient"),
                PathBuf::from("/home/u/Apps/AI-Potluck.AppImage")
            ]
        );
        // a dev build deletes no binary
        assert!(plan(vec![], home, ID, &dev()).is_empty());
    }

    #[test]
    fn a_package_manager_install_and_a_dev_build_are_left_alone_and_say_so() {
        let tmp = std::env::temp_dir();
        if cfg!(target_os = "linux") {
            let pkg = AppInstall::detect(Path::new("/usr/bin/aipotluck-local-client-gui"), None);
            assert_eq!(pkg.kind(), "system-package");
            assert!(pkg.note().unwrap().contains("apt remove"));
            let devb = AppInstall::detect(&tmp.join("target/debug/x"), None);
            assert_eq!(devb.kind(), "unmanaged");
            let opt_checkout = AppInstall::detect(
                Path::new("/opt/data/aipotluck-local-client-gui/src-tauri/target/release/app"),
                None,
            );
            assert_eq!(opt_checkout.kind(), "unmanaged");
            assert!(devb.note().unwrap().contains("stays"));
        }
    }

    #[test]
    fn an_appimage_is_recognised_from_its_variable() {
        if cfg!(target_os = "linux") {
            let f = std::env::temp_dir().join("aip-uninstall-test.AppImage");
            std::fs::write(&f, b"x").unwrap();
            let app = AppInstall::detect(Path::new("/tmp/.mount_x/usr/bin/app"), Some(f.clone()));
            assert_eq!(app, AppInstall::AppImage { file: f.clone() });
            std::fs::remove_file(&f).unwrap();
            // a stale variable pointing nowhere isn't trusted
            assert_ne!(
                AppInstall::detect(Path::new("/tmp/x"), Some(f)).kind(),
                "appimage"
            );
        }
    }

    #[cfg(unix)]
    #[test]
    fn the_cleanup_process_waits_for_the_app_to_exit_then_deletes() {
        let dir = std::env::temp_dir().join(format!("aip-cleanup-{}", std::process::id()));
        std::fs::create_dir_all(dir.join("org.aipotluck.localclient")).unwrap();
        let target = dir.join("org.aipotluck.localclient");
        let mut stand_in = Command::new("sleep").arg("1").spawn().unwrap();
        let mut c = cleanup_command(stand_in.id(), &dev(), &[target.clone()])
            .spawn()
            .unwrap();
        std::thread::sleep(std::time::Duration::from_millis(400));
        assert!(target.exists(), "deleted before the app exited");
        stand_in.wait().unwrap();
        c.wait().unwrap();
        assert!(!target.exists());
        std::fs::remove_dir_all(&dir).ok();
    }
}
