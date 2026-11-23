from __future__ import annotations
import json,os,subprocess,sys,urllib.request
import github_ci_probe as ci
run_id,expected_sha=sys.argv[1:3]
run=ci.get("/actions/runs/"+run_id)
assert run["head_sha"]==expected_sha
assert run["head_branch"]=="main" and run["name"]=="Build and Sync to Release Repo"
assert run["status"] in {"queued","in_progress","pending","requested","waiting"}
env={**os.environ,"GIT_TERMINAL_PROMPT":"0","GCM_INTERACTIVE":"Never"}
result=subprocess.run(["git","credential","fill"],input="protocol=https\nhost=github.com\npath="+ci.REPO+".git\n\n",capture_output=True,text=True,env=env,check=True)
fields=dict(line.split("=",1) for line in result.stdout.splitlines() if "=" in line)
request=urllib.request.Request("https://api.github.com/repos/"+ci.REPO+"/actions/runs/"+run_id+"/cancel",data=b"",method="POST",headers={"Authorization":"Bearer "+fields["password"],"Accept":"application/vnd.github+json"})
with urllib.request.build_opener(ci.NoRedirect()).open(request,timeout=30) as response:
    print(json.dumps({"cancelled_duplicate_main_run":run_id,"sha":expected_sha,"http_status":response.status}))
