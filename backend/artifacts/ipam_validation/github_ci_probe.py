from __future__ import annotations
import json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
REPO = "chaojifeixia-007/netsops"
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def get(path):
    env = {**os.environ, "GIT_TERMINAL_PROMPT":"0", "GCM_INTERACTIVE":"Never"}
    credential = subprocess.run(["git","credential","fill"],input="protocol=https\nhost=github.com\npath="+REPO+".git\n\n",capture_output=True,text=True,env=env,check=True)
    fields = dict(line.split("=",1) for line in credential.stdout.splitlines() if "=" in line)
    token = fields.get("password", "")
    if not token: raise RuntimeError("Git credential helper returned no usable credential")
    req=urllib.request.Request("https://api.github.com/repos/"+REPO+path,headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"})
    try:
        opener=urllib.request.build_opener(NoRedirect())
        with opener.open(req,timeout=30) as res:
            payload=res.read()
            return json.loads(payload) if "json" in res.headers.get("Content-Type","") else payload.decode("utf-8",errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (301,302,303,307,308) and path.endswith("/logs"):
            location=exc.headers.get("Location", "")
            parsed=urllib.parse.urlparse(location)
            host=parsed.hostname or ""
            if parsed.scheme!="https" or not (host.endswith(".blob.core.windows.net") or host.endswith(".actions.githubusercontent.com") or host.endswith(".githubusercontent.com")):
                raise RuntimeError("Unexpected log redirect host") from None
            clean_req=urllib.request.Request(location,headers={"User-Agent":"Nexora-CI-verification"})
            with urllib.request.urlopen(clean_req,timeout=30) as res:
                return res.read().decode("utf-8", errors="replace")
        raise RuntimeError("GitHub API HTTP "+str(exc.code)) from None
if __name__ == "__main__":
    mode=sys.argv[1]
    if mode=="runs":
        result=get("/actions/runs?head_sha="+sys.argv[2]+"&per_page=100")
        print(json.dumps([{k:r.get(k) for k in ("id","name","head_sha","head_branch","status","conclusion","html_url","run_attempt","event")} for r in result["workflow_runs"]],indent=2))
    elif mode=="jobs":
        result=get("/actions/runs/"+sys.argv[2]+"/jobs?per_page=100")
        print(json.dumps([{k:r.get(k) for k in ("id","name","status","conclusion","html_url","steps")} for r in result["jobs"]],indent=2))
    elif mode=="logs":
        print(get("/actions/jobs/"+sys.argv[2]+"/logs"))
