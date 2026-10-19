//! The GUI's own preferences -- today only the AI Potluck server one-click pairing talks to.
//!
//! Stored as `<data_home>/aipotluck/gui-settings.json`, beside the GUI runtime and outside
//! upstream's config dir, so nothing upstream reads is ever changed by it. No secret is ever
//! written here.
//!
//! The override is for testing against a non-production server (develop, a local dev server); a
//! normal install never sets it, and then upstream's own default (aipotluck.org) applies. Whether
//! a value is acceptable is upstream's call (`pairing.resolve_server_url`, via the gui_server.py
//! sidecar), so this module only stores and trims; it never decides what a valid server is.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Default, Clone, PartialEq, Serialize, Deserialize)]
pub struct Settings {
    /// Passed to `cli login --server-url`. None = upstream's default.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server_url: Option<String>,
}

pub fn path() -> PathBuf {
    crate::paths::data_home()
        .join("aipotluck")
        .join("gui-settings.json")
}

/// Missing or unreadable settings are the defaults, never an error: a broken preferences file must
/// not stop anyone pairing with the production server.
pub fn load_from(path: &Path) -> Settings {
    fs::read(path)
        .ok()
        .and_then(|b| serde_json::from_slice::<Settings>(&b).ok())
        .map(Settings::normalised)
        .unwrap_or_default()
}

pub fn save_to(path: &Path, settings: &Settings) -> Result<(), String> {
    let settings = settings.clone().normalised();
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    if settings == Settings::default() {
        // Back to the defaults: no file at all, so nothing lingers to surprise anyone later.
        return match fs::remove_file(path) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e.to_string()),
            _ => Ok(()),
        };
    }
    let tmp = path.with_extension("json.tmp");
    fs::write(
        &tmp,
        serde_json::to_vec_pretty(&settings).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    fs::rename(&tmp, path).map_err(|e| e.to_string())
}

impl Settings {
    fn normalised(mut self) -> Self {
        self.server_url = self
            .server_url
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp() -> PathBuf {
        let d = std::env::temp_dir().join(format!(
            "gui-settings-test-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = fs::remove_dir_all(&d);
        d.join("gui-settings.json")
    }

    #[test]
    fn a_missing_or_corrupt_file_means_upstreams_default_server() {
        let p = tmp();
        assert_eq!(load_from(&p), Settings::default());
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(&p, b"{not json").unwrap();
        assert_eq!(load_from(&p).server_url, None);
    }

    #[test]
    fn an_override_round_trips_trimmed() {
        let p = tmp();
        save_to(
            &p,
            &Settings {
                server_url: Some("  https://develop.aipotluck.org \n".into()),
            },
        )
        .unwrap();
        assert_eq!(
            load_from(&p).server_url.as_deref(),
            Some("https://develop.aipotluck.org")
        );
    }

    #[test]
    fn clearing_the_override_removes_the_file_so_no_stale_server_lingers() {
        let p = tmp();
        save_to(
            &p,
            &Settings {
                server_url: Some("http://localhost:5173".into()),
            },
        )
        .unwrap();
        assert!(p.exists());
        save_to(
            &p,
            &Settings {
                server_url: Some("   ".into()),
            },
        )
        .unwrap();
        assert!(!p.exists());
        assert_eq!(load_from(&p), Settings::default());
    }
}
