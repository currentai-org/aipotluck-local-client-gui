# Bundled fonts

The Alpha design system's typefaces, bundled so the app renders the same type as aipotluck.org
with no network fetch. They are the one kind of third-party binary this repo commits: the SIL Open
Font License explicitly permits redistribution and bundling (OFL §2). Copied from
`aipotluck-local-client-android/app/src/main/res/font/`, which took them from `google/fonts`.

| File | Family | Role | Source | License |
| --- | --- | --- | --- | --- |
| `plus_jakarta_sans.ttf` | Plus Jakarta Sans (variable, `wght`) | Font 1 — everything by default | `google/fonts` `ofl/plusjakartasans/PlusJakartaSans[wght].ttf` | OFL 1.1 — `OFL-PlusJakartaSans.txt` |
| `dm_mono_regular.ttf` | DM Mono Regular | Font 2 — technical/meta | `google/fonts` `ofl/dmmono/DMMono-Regular.ttf` | OFL 1.1 — `OFL-DMMono.txt` |
| `dm_mono_medium.ttf` | DM Mono Medium | Font 2 — labels, CTAs | `google/fonts` `ofl/dmmono/DMMono-Medium.ttf` | OFL 1.1 — `OFL-DMMono.txt` |

SHA-256 (identical to the Android repo's recorded values):

```
89b3fb38aa0d275d7a731d0d817a4f1622b316b4d7fbdedcf02ee9099ff68bc8  plus_jakarta_sans.ttf
55b4c98f123daebb3ed27947ba47b2af00554fc6284d639a540bcef5e6258ad2  dm_mono_regular.ttf
fd327daf461db87b44a87def475d251bf03b997f7c07d9680592d75dbbfaad0b  dm_mono_medium.ttf
```

Font 3 (Noto Serif) is not bundled: the spec uses it for the onboarding headline only, which this
app doesn't have. `--ds-font-serif` falls back to Georgia.
