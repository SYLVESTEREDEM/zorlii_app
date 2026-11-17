import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                     "Node.js and mobile TypeScript are needed")
class ThreadRefreshTests(unittest.TestCase):
    def run_node(self, script):
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_final_pages_and_notification_target(self):
        helper = (ROOT / "mobile" / "threadPagination.ts").read_text(encoding="utf-8")
        script = """
        const assert=require('node:assert/strict'),ts=require(%s),exports={};
        new Function('exports',ts.transpile(%s,{module:ts.ModuleKind.CommonJS}))(exports);
        const post={reply_count:2};
        (async()=>{
          let calls=[];
          const noNew=await exports.readThreadPages(async cursor=>{
            calls.push(cursor);
            if(calls.length>1)throw Error('unexpected extra request');
            return {post,replies:[{id:1,body:'edited'}],has_more:false,next_after_id:null};
          },post,false);
          assert.deepEqual(calls,[undefined]);
          assert.equal(noNew.replies[0].body,'edited');
          assert.equal(noNew.hasMore,false);
          calls=[];
          const lastPage=await exports.readThreadPages(async cursor=>{
            calls.push(cursor);
            if(calls.length>2)throw Error('unexpected extra request');
            return cursor===undefined
              ? {post,replies:[{id:1}],has_more:true,next_after_id:1}
              : {post,replies:[{id:2}],has_more:false,next_after_id:null};
          },post,false);
          assert.deepEqual(calls,[undefined,1]);
          assert.deepEqual(lastPage.replies.map(r=>r.id),[1,2]);
          calls=[];
          const target=await exports.readThreadPages(async cursor=>{
            calls.push(cursor);
            return cursor===undefined ? {post,replies:[{id:1}],has_more:true,next_after_id:1}
              : cursor===1 ? {post,replies:[{id:2}],has_more:true,next_after_id:2}
              : {post,replies:[{id:3}],has_more:false,next_after_id:null};
          },post,true,3);
          assert.deepEqual(calls,[undefined,1,2]);
          assert.equal(target.replies.at(-1).id,3);
        })().catch(error=>{console.error(error);process.exitCode=1});
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")), json.dumps(helper))
        self.run_node(script)

    def test_web_refresh_reconciles_loaded_pages_and_keeps_draft_on_failure(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        refresh = "async function refreshThread({initial=false}" + html.split(
            "async function refreshThread({initial=false}", 1
        )[1].split("\n    async function loadMoreThreadReplies()", 1)[0]
        script = """
        const assert=require('node:assert/strict');
        let state, calls, failPage;
        const harness=new Function('api','drawThread','requestAnimationFrame','document',%s+
          ';return {refreshThread,setState:value=>threadState=value};');
        let pages;
        const runner=harness(async path=>{
          calls.push(path);
          if(calls.length>3)throw Error('unexpected extra request');
          if(failPage && path.includes('after_id'))throw Error('network failed');
          return path.includes('after_id') ? pages[1] : pages[0];
        },()=>{},()=>{}, {querySelector:()=>null});
        async function run(first,second,fail=false,initial=false,target=null){
          calls=[];failPage=fail;pages=[first,second];
          state={id:1,post:{reply_count:3},replies:[{id:1,body:'old'},{id:2,body:'deleted'},{id:3,body:'old'}],
            hasMore:false,nextAfterId:3,replyId:target,error:'',draft:'keep draft'};
          runner.setState(state);await runner.refreshThread({initial});return state;
        }
        (async()=>{
          const first={post:{reply_count:2},replies:[{id:1,body:'edited'}],has_more:true,next_after_id:1};
          const last={post:{reply_count:2},replies:[{id:3,body:'new'}],has_more:false,next_after_id:null};
          let result=await run(first,last);
          assert.deepEqual(result.replies,[{id:1,body:'edited'},{id:3,body:'new'}]);
          assert.equal(result.hasMore,false);assert.equal(calls.length,2);
          result=await run({post:{reply_count:1},replies:[{id:1}],has_more:false,next_after_id:null},null);
          assert.equal(calls.length,1);assert.deepEqual(result.replies,[{id:1}]);
          result=await run(first,last,true);
          assert.equal(result.error,'network failed');
          assert.deepEqual(result.replies.map(r=>r.id),[1,2,3]);assert.equal(result.nextAfterId,3);
          assert.equal(result.draft,'keep draft');
          result=await run(first,last,false,true,3);
          assert.equal(calls.length,2);assert.equal(result.replies.at(-1).id,3);
        })().catch(error=>{console.error(error);process.exitCode=1});
        """ % json.dumps("let threadState;\n" + refresh)
        self.run_node(script)

    def test_native_refresh_replaces_loaded_replies_only_after_all_pages_succeed(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        helper = (ROOT / "mobile" / "threadPagination.ts").read_text(encoding="utf-8")
        refresh = "async function refreshThread(" + mobile.split("async function refreshThread(", 1)[1].split(
            "\n  threadRefreshLatestRef.current", 1
        )[0]
        script = """
        const assert=require('node:assert/strict'),ts=require(%s),exports={};
        new Function('exports',ts.transpile(%s,{module:ts.ModuleKind.CommonJS}))(exports);
        const source=ts.transpile(%s);
        async function run(fail){
          const previous=[{id:1,body:'old'},{id:2,body:'deleted'},{id:3,body:'old'}];
          let visible=previous,error='',calls=0;
          const threadRequestRef={current:1},threadRefreshBusyRef={current:false},
            threadLoadingMoreRef={current:false},threadRefreshAgainRef={current:false},threadRefreshLatestRef={current:async()=>{}};
          const threadPost={id:1,reply_count:3};
          const request=async path=>{
            calls++;if(calls>2)throw Error('unexpected extra request');
            if(path.includes('after_id')){
              if(fail)throw Error('offline');
              return {post:threadPost,replies:[{id:3,body:'new'}],has_more:false,next_after_id:null};
            }
            return {post:threadPost,replies:[{id:1,body:'edited'}],has_more:true,next_after_id:1};
          };
          const noop=()=>{};
          const refresh=new Function('threadRequestRef','threadRefreshBusyRef','threadLoadingMoreRef',
            'threadRefreshAgainRef','threadRefreshLatestRef','threadPost','request','readThreadPages',
            'setThreadLoading','setThreadRefreshing','setThreadError','setThreadPost','setThreadReplies',
            'setThreadHasMore','setThreadNextAfterId','requestAnimationFrame',source+';return refreshThread;')(
            threadRequestRef,threadRefreshBusyRef,threadLoadingMoreRef,threadRefreshAgainRef,threadRefreshLatestRef,
            threadPost,request,exports.readThreadPages,noop,noop,value=>error=value,noop,value=>visible=value,
            noop,noop,noop);
          await refresh();
          return {previous,visible,error,calls};
        }
        (async()=>{
          const success=await run(false);
          assert.deepEqual(success.visible,[{id:1,body:'edited'},{id:3,body:'new'}]);
          assert.equal(success.calls,2);
          const failure=await run(true);
          assert.equal(failure.visible,failure.previous);
          assert.equal(failure.error,'offline');
        })().catch(error=>{console.error(error);process.exitCode=1});
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")), json.dumps(helper), json.dumps(refresh))
        self.run_node(script)
