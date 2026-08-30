# libmpv

`libmpv-2.dll` belongs in this directory. It is **not committed** — it is ~115 MB, and shipping
someone else's build artefact in source control is the wrong place for it.

`winnotix/core/mpvloader.py` looks here first, then falls back to anything on `%PATH%`.

## Getting it

Windows libmpv builds come from [shinchiro/mpv-winbuild-cmake][rel] — download the
`mpv-dev-x86_64-<date>-git-<sha>.7z` asset from the latest release and extract `libmpv-2.dll` here.

[rel]: https://github.com/shinchiro/mpv-winbuild-cmake/releases

```powershell
# From the repo root:
$r = Invoke-RestMethod "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest" `
     -Headers @{ "User-Agent" = "winnotix" }
$asset = $r.assets | Where-Object { $_.name -like "mpv-dev-x86_64-2*" } | Select-Object -First 1
Invoke-WebRequest $asset.browser_download_url -OutFile "$env:TEMP\mpv-dev.7z" -UseBasicParsing
7z x "$env:TEMP\mpv-dev.7z" -o"$env:TEMP\mpv-dev" -y
Copy-Item "$env:TEMP\mpv-dev\libmpv-2.dll" "vendor\libmpv\libmpv-2.dll"
```

## Verifying

```powershell
.\.venv\Scripts\python.exe -c "from winnotix.core.mpvloader import load_mpv; m=load_mpv().MPV(); print(m.mpv_version); m.terminate()"
```

Known good: **mpv v0.41.0-1012-ge8673660a** (release `20260830`), which is what Phase 0 was
validated against.

## Note for packaging (Phase 4)

The dev build's DLL is unstripped and ~115 MB. Strip it or source a stripped build before
distribution — see roadmap.md §6.
