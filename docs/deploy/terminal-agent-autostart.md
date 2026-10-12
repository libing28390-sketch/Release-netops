# Windows Terminal Agent startup

The packaged `NexoraTerminalAgent.exe` registers itself in the current user's
Windows startup entries the first time it is launched. The registration uses
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, so administrator
privileges are not required.

The startup command includes `--managed-start`. A managed launch skips the
registration step and starts the loopback service directly.

For troubleshooting or one-off runs:

```powershell
.\NexoraTerminalAgent.exe --no-autostart
.\NexoraTerminalAgent.exe --unregister-autostart
```

The source installation script uses the same current-user startup mechanism.
The agent remains loopback-only on `127.0.0.1:17890`.
