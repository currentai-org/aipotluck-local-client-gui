//! The pairing JSON aipotluck.org's "Copy" button puts on the clipboard.
//!
//! Upstream's `cli._parse_credentials_json` is the authority on what is accepted -- the GUI hands
//! the raw text to `cli login --credentials-file`, so upstream re-validates it. This module only
//! exists to recognise the shape quickly enough to offer a one-click "Pair" button when the
//! clipboard holds it, and to never surface anything else from the clipboard.

use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PairingPreview {
    /// Shown to the user so they can tell which device/tunnel they're pairing to.
    pub tunnel_id: String,
    pub tunnel_endpoint: String,
}

/// Returns a preview only when `raw` is a JSON object with non-empty string `tunnelId`,
/// `tunnelSecret` and `tunnelEndpoint` -- the same rule upstream applies. Never returns the secret.
pub fn recognise(raw: &str) -> Option<PairingPreview> {
    let trimmed = raw.trim();
    if !trimmed.starts_with('{') || trimmed.len() > 16 * 1024 {
        return None;
    }
    let value: serde_json::Value = serde_json::from_str(trimmed).ok()?;
    let obj = value.as_object()?;
    let get = |k: &str| -> Option<String> {
        obj.get(k)?
            .as_str()
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
    };
    get("tunnelSecret")?;
    Some(PairingPreview {
        tunnel_id: get("tunnelId")?,
        tunnel_endpoint: get("tunnelEndpoint")?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recognises_the_copy_button_shape_and_never_returns_the_secret() {
        let p = recognise(r#"{"tunnelId":"t1","tunnelSecret":"s3cret","tunnelEndpoint":"https://pangolin.example"}"#)
            .expect("recognised");
        assert_eq!(p.tunnel_id, "t1");
        assert_eq!(p.tunnel_endpoint, "https://pangolin.example");
        assert!(!format!("{p:?}").contains("s3cret"));
    }

    #[test]
    fn unrelated_clipboard_text_is_never_offered_as_a_pairing() {
        assert_eq!(recognise("hello world"), None);
        assert_eq!(recognise(r#"{"tunnelId":"t1","tunnelEndpoint":"e"}"#), None);
        assert_eq!(
            recognise(r#"{"tunnelId":"","tunnelSecret":"s","tunnelEndpoint":"e"}"#),
            None
        );
        assert_eq!(
            recognise(r#"{"tunnelId":1,"tunnelSecret":"s","tunnelEndpoint":"e"}"#),
            None
        );
        assert_eq!(
            recognise(r#"["tunnelId","tunnelSecret","tunnelEndpoint"]"#),
            None
        );
    }

    #[test]
    fn extra_fields_are_tolerated_like_upstream() {
        assert!(recognise(
            r#"{"tunnelId":"a","tunnelSecret":"b","tunnelEndpoint":"c","name":"x"}"#
        )
        .is_some());
    }
}
