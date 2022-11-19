import random
import subprocess

# with open('./Webshare 100 proxies.txt') as f:
#     raw = f.read().split()

with open('./proxies.txt') as f:
    raw = f.read().split()
    
proxies = []
    
for string in raw:
    ip, port, login, pw = string.split(sep=':')
    proxies.append(f"http://{login}:{pw}@{ip}:{port}")


to_use = random.sample(proxies, 10)


commands = []
for i in range(2):
    call = (
        f'python processor.py --config="windows_config{i}.json" '
        f'--proxy_monitor="{to_use[2*i]}" '
        f'--proxy_apply="{to_use[2*i+1]}" '
        f'--publish=0 --remove_previous=1 --fake_monitor={random.randint(5, 10)} --infinite=0'
    )
    
    commands.append(call)

procs = [subprocess.Popen(i, shell=True) for i in commands]

for p in procs:
    p.wait()