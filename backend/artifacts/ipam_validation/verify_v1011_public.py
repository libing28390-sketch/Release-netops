from __future__ import annotations
import json,urllib.request,urllib.error
BASE="https://api.github.com/repos/libing28390-sketch/Release-netops"
def get(path):
    req=urllib.request.Request(BASE+path,headers={"Accept":"application/vnd.github+json","User-Agent":"Nexora-release-validation"})
    with urllib.request.urlopen(req,timeout=30) as response: return json.load(response)
if __name__=="__main__":
    release=get("/releases/tags/v1.0.11")
    print(json.dumps({k:release.get(k) for k in ("tag_name","name","html_url","draft","prerelease","target_commitish")},ensure_ascii=False))
    print(json.dumps([{"name":a["name"],"size":a["size"],"state":a["state"],"url":a["browser_download_url"]} for a in release["assets"]],ensure_ascii=False))
    assets={item["name"]:item for item in release["assets"]}
    assert {"NetOps-Linux-Ubuntu.zip","NexoraTerminalAgent.exe"} <= set(assets)
    assert all(assets[name]["state"]=="uploaded" and assets[name]["size"]>0 for name in ("NetOps-Linux-Ubuntu.zip","NexoraTerminalAgent.exe"))
    assert get("/releases/latest")["tag_name"]=="v1.0.11"
    assert get("/git/ref/heads/main")["object"]["sha"]==get("/git/ref/tags/v1.0.11")["object"]["sha"]
    for ref in ("heads/main","tags/v1.0.11"):
        print(ref,json.dumps(get("/git/ref/"+ref)["object"]))
    for ref in ("main","v1.0.11"):
        for path in ("package.json","backend/core/version.py","README.md","docs/deploy/release-notes.md"):
            req=urllib.request.Request("https://raw.githubusercontent.com/libing28390-sketch/Release-netops/"+ref+"/"+path,headers={"User-Agent":"Nexora-release-validation"})
            with urllib.request.urlopen(req,timeout=30) as response: text=response.read().decode("utf-8-sig")
            if path=="package.json": assert json.loads(text)["version"]=="1.0.11"
            elif path.endswith("version.py"): assert 'VERSION = "1.0.11"' in text
            elif path=="README.md": assert "v1.0.11" in text
            else: assert text.startswith("# Nexora v1.0.11")
        print("PASS public version/readme/notes",ref)
