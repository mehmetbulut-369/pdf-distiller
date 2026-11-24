# Signing the packaged app

Without a signature the app works, but the first start is harder than it should be:

- **macOS** (downloaded `.dmg`): "PDF Distiller can't be opened because Apple cannot check it for malicious
  software." The user has to right-click → Open, or allow it in System Settings → Privacy & Security.
- **Windows**: SmartScreen shows "Windows protected your PC"; the user has to click "More info" → "Run anyway".

`packaging/build.py` signs when credentials are present and builds unsigned otherwise, so nothing changes
until they are set.

## macOS: Developer ID + notarization

1. Join the Apple Developer Program (paid, yearly) and create a **Developer ID Application** certificate
   (Xcode → Settings → Accounts, or developer.apple.com → Certificates).
2. Create an app-specific password at account.apple.com → Sign-In and Security.
3. Local build:

   ```bash
   xcrun notarytool store-credentials pdf-distiller --apple-id YOU@example.com --team-id TEAMID
   MACOS_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" MACOS_NOTARY_PROFILE=pdf-distiller python packaging/build.py
   ```

   The script signs the `.app` with the hardened runtime (`packaging/entitlements.plist`), builds and signs
   the `.dmg`, sends it to Apple, waits for the result and staples the ticket.
4. Release workflow: export the certificate as `.p12` and add these repository secrets:
   `MACOS_CERT_P12` (base64 of the file), `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY`, `APPLE_ID`,
   `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD`.

Check a result: `spctl -a -vv -t install dist/PDF-Distiller-macOS.dmg` should say `accepted, source=Notarized Developer ID`.

## Windows: code-signing certificate

Any Authenticode certificate works (an OV/EV certificate from a CA, or Azure Trusted Signing). SmartScreen
trusts a new certificate after enough downloads; an EV certificate is trusted at once.

- Local build: `WINDOWS_SIGN_PFX=C:\path\cert.pfx WINDOWS_SIGN_PASSWORD=... python packaging/build.py`
  (needs `signtool.exe` from the Windows SDK).
- Release workflow: secrets `WINDOWS_CERT_PFX` (base64 of the `.pfx`) and `WINDOWS_CERT_PASSWORD`.
