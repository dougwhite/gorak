# Gorak over SSH

1. Configure OpenSSH access to your OpenROAD windows development machine

2. Create a directory to host the gorak ssh commands e.g `C:\Development\gorak`

3. Copy the `*.bat` files from this folder into your gorak host path

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