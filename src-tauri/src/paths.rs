//! Runtime layout: where the bundled Python and the upstream CLI source live once unpacked.
//!
//! The OS service the upstream installer registers records the interpreter path and the upstream
//! source path in its unit file (`ExecStart=<python> <upstream>/aipotluck/service/aipotluck_service.py`).
//! Those paths must outlive the GUI process, so they can never point inside the app bundle: an
//! AppImage mounts at a random `/tmp/.mount_*` path and macOS App Translocation moves quarantined
//! apps to a random path, both gone after the app quits. So the bundled runtime is unpacked once
//! into a stable per-user directory and everything runs from there.

use std::path::{Path, PathBuf};

pub fn data_home() -> PathBuf {
    if cfg!(target_os = "windows") {
        if let Some(v) = std::env::var_os("LOCALAPPDATA") {
            return PathBuf::from(v);
        }
    }
    if cfg!(target_os = "macos") {
        return home().join("Library").join("Application Support");
    }
    match std::env::var_os("XDG_DATA_HOME") {
        Some(v) if !v.is_empty() => PathBuf::from(v),
        _ => home().join(".local").join("share"),
    }
}

pub fn home() -> PathBuf {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// `<data_home>/aipotluck/gui-runtime` -- sits beside upstream's own `<data_home>/aipotluck/llama.cpp`.
pub fn runtime_root() -> PathBuf {
    if let Some(v) = std::env::var_os("AIPOTLUCK_GUI_RUNTIME_DIR") {
        return PathBuf::from(v);
    }
    data_home().join("aipotluck").join("gui-runtime")
}

pub fn python_dir(root: &Path, python_tag: &str) -> PathBuf {
    root.join(format!("python-{python_tag}"))
}

pub fn python_exe(python_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        python_dir.join("python").join("python.exe")
    } else {
        python_dir.join("python").join("bin").join("python3")
    }
}

pub fn upstream_dir(root: &Path, upstream_sha: &str) -> PathBuf {
    let short: String = upstream_sha.chars().take(12).collect();
    root.join(format!("upstream-{short}"))
}
