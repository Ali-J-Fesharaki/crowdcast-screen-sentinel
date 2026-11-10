import subprocess
import os
import time

env = os.environ.copy()
env['WAYLAND_DISPLAY'] = 'wayland-0'
env['XDG_RUNTIME_DIR'] = '/run/user/1000'
env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/run/user/1000/bus'
env['XDG_SESSION_TYPE'] = 'wayland'

# Call Event on id 22
cmd = [
    'gdbus', 'call', '--session',
    '--dest', 'org.kde.StatusNotifierItem-229701-1',
    '--object-path', '/MenuBar',
    '--method', 'com.canonical.dbusmenu.Event',
    '22', 'clicked', '<int32 0>', str(int(time.time()))
]
res = subprocess.run(cmd, env=env, capture_output=True, text=True)
print('Event return:', res.stdout, res.stderr)
