# Gorak over SSH

These helper files are packaged with `gorak` and used by `gorak remote install`,
so the command works from a built distribution as well as a source checkout.

1. Configure OpenSSH access to your OpenROAD windows development machine

2. Create a directory to host the gorak ssh commands e.g `C:\Development\gorak`

3. Copy the helper files from this folder into your gorak host path

   From the local gorak command you can do this with:
   ```
   uv run gorak remote install \
     --user [user] \
     --host [hostname-or-ip] \
     --gorak-root 'C:\Development\gorak'
   ```

   When run inside a Gorak project, `remote install` can read the user, host,
   and remote root from the project `.env`.

4. Set an environment variable? `GORAK_REMOTE_SSH=???`

> TODO: Figure out how the gorak client will determine to use these over a local w4gldev.exe?

example usage:
```
ssh -T [user]@[hostname-or-ip] 'c:\Development\gorak\backup-component.bat [vnode]::[database] [application] [component]'
```

Would export the component to:
```
C:\Development\gorak\repos\[vnode]\[database]\[application]\[component].xml
```

To list applications in an OpenROAD source database:
```
ssh -T [user]@[hostname-or-ip] 'c:\Development\gorak\get-app-list.bat [vnode] [database]'
```

To list components in one OpenROAD application:
```
ssh -T [user]@[hostname-or-ip] 'c:\Development\gorak\get-component-list.bat [vnode] [database] [application]'
```
