Real output of Houdini 22.0.466 on Windows 11 without a licence (2026-10-24: no SideFX
sign-in, no installed licences). Host names, addresses and server codes are redacted;
nothing else is changed.

- `hython-no-licence.log`: the launch log of `houdini_connect {launch: {mode: headless}}`
  (`hython -m hocuspocus.host`, exit code 3). A plain `hython -c ...` prints the same two
  lines to stderr and also exits with 3.
- `sesictrl-diagnostic-logged-out.txt`: `sesictrl diagnostic` (exit code 0).
- `hserver-l.txt`: `hserver -l` (exit code 0).

houdinifx prints nothing. About 1 s after it starts, it starts `hkey.exe` (the License
Administrator) as a child process and shows a window titled `Unable to Acquire a License`.
It exits with code 3 after 3-15 s.
