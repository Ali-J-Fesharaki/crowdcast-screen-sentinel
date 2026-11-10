import subprocess
import os

env = os.environ.copy()
env['WAYLAND_DISPLAY'] = 'wayland-0'
env['XDG_RUNTIME_DIR'] = '/run/user/1000'
env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/run/user/1000/bus'
env['XDG_SESSION_TYPE'] = 'wayland'

cmd = ['gdbus', 'call', '--session', '--dest', 'org.kde.StatusNotifierItem-229701-1', '--object-path', '/MenuBar', '--method', 'com.canonical.dbusmenu.GetLayout', '0', '3', '["label"]']
res = subprocess.run(cmd, env=env, capture_output=True, text=True)
print('STDOUT:', res.stdout)
print('STDERR:', res.stderr)
