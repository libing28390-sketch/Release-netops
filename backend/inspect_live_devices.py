import urllib.request, json

try:
    req = urllib.request.Request('http://localhost:5400/api/monitoring/network-devices')
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        print(f"Total devices in /api/monitoring/network-devices: {len(data)}")
        for d in data:
            intfs = d.get('interface_data') or []
            print(f"Device: {d.get('hostname')} (ID: {d.get('id')}, vendor: {d.get('vendor')}, model: {d.get('model')}) -> total intfs: {len(intfs)}")
            up_intfs = [i.get('name') for i in intfs if str(i.get('status')).lower() in ['up', '1', 'true']]
            print(f"   UP intfs ({len(up_intfs)}): {up_intfs}")
            print(f"   All intf names ({len(intfs)}): {[i.get('name') for i in intfs[:30]]}")
except Exception as e:
    print("Error:", e)
