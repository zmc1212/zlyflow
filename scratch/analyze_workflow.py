import requests
import json

r = requests.get('http://192.168.10.54:8188/object_info/MiniMaxH3Director')
info = r.json()['MiniMaxH3Director']
print("Input keys:", list(info['input'].keys()))

if 'optional' in info['input']:
    print("Optional inputs:")
    for k, v in info['input']['optional'].items():
        print(f"  {k}: {v}")

if 'hidden' in info['input']:
    print("Hidden inputs:")
    for k, v in info['input']['hidden'].items():
        print(f"  {k}: {v}")
