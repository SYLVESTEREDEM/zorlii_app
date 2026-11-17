import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MobilePushRegistrationTests(unittest.TestCase):
    def test_android_notification_permission_is_declared(self):
        config = json.loads((ROOT / "mobile" / "app.json").read_text(encoding="utf-8"))
        manifest = (ROOT / "mobile" / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn("android.permission.POST_NOTIFICATIONS", config["expo"]["android"]["permissions"])
        self.assertIn('<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>', manifest)
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('if (!token || !me?.terms_accepted) return;', mobile)

    @unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                         "Node.js and mobile TypeScript are needed")
    def test_permission_prompt_order_denial_blocking_and_cached_retry(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        registration = "async function registerPushToken" + mobile.split("async function registerPushToken", 1)[1].split(
            "\n  async function loadFeed", 1
        )[0]
        script = """
        const assert=require('node:assert/strict'),ts=require(%s),code=ts.transpile(%s);
        function harness({permission={status:'granted'},requested=permission,project=true,cached=null}={}) {
          const events=[],refs={pushSessionRef:{current:'session'},pushSessionGenerationRef:{current:1},
            pushTokenRef:{current:cached},pushRegistrationPromiseRef:{current:null},pushRegistrationOwnerRef:{current:''},
            pushRegistrationGenerationRef:{current:0},pushPostingRef:{current:false},
            pushRetryPendingRef:{current:false},pushReturnRetryUsedRef:{current:false}};
          const Notifications={AndroidImportance:{HIGH:1},
            setNotificationChannelAsync:async()=>{events.push('channel')},
            getPermissionsAsync:async()=>{events.push('get');return permission},
            requestPermissionsAsync:async()=>{events.push('ask');return requested},
            getExpoPushTokenAsync:async()=>{events.push('token');return {data:'synthetic'}}};
          const Constants={get easConfig(){events.push('project');return project?{projectId:'test'}:null},expoConfig:null};
          const deps={Notifications,Platform:{OS:'android'},Device:{isDevice:true},Constants,
            canRegisterPushToken:()=>true,isTransientPushServiceUnavailable:()=>false,
            retryTransientPushOperation:op=>op(),API_URL:'http://local.test',
            fetch:async()=>{events.push('post');return {ok:true}},warnPushCleanup:()=>{throw Error('cleanup')}};
          const register=new Function(...Object.keys(refs),...Object.keys(deps),code+';return registerPushToken')(
            ...Object.values(refs),...Object.values(deps));
          return {register,refs,events,Notifications};
        }
        (async()=>{
          let h=harness({permission:{status:'undetermined',canAskAgain:true},
            requested:{status:'granted',canAskAgain:true},project:false});
          await assert.rejects(h.register('session'),/EAS project/);
          assert.deepEqual(h.events,['channel','get','ask','project']);
          h=harness({permission:{status:'undetermined',canAskAgain:true},
            requested:{status:'granted',canAskAgain:true}});
          assert.equal(await h.register('session'),true);
          assert.deepEqual(h.events,['channel','get','ask','project','token','post']);
          h=harness({permission:{status:'denied',canAskAgain:true}});
          assert.equal(await h.register('session',true),false);
          assert.deepEqual(h.events,['channel','get','ask']);
          h=harness({permission:{status:'denied',canAskAgain:false},cached:'cached'});
          assert.equal(await h.register('session',true),'blocked');
          assert.deepEqual(h.events,['channel','get']);
          assert.equal(h.refs.pushTokenRef.current,'cached');
          h=harness({permission:{status:'granted'},cached:'cached'});
          assert.equal(await h.register('session',true),true);
          assert.deepEqual(h.events,['channel','get']);
          h=harness({permission:{status:'denied',canAskAgain:false}});
          assert.equal(await h.register('session'),false);
          assert.deepEqual(h.events,['channel','get']);

          h=harness({permission:{status:'undetermined',canAskAgain:true}});
          let finishPrompt,promptStarted;
          const started=new Promise(resolve=>promptStarted=resolve);
          h.Notifications.requestPermissionsAsync=()=>{h.events.push('ask');promptStarted();return new Promise(resolve=>finishPrompt=resolve)};
          const pending=h.register('session');
          await started;
          h.refs.pushSessionGenerationRef.current++;
          finishPrompt({status:'granted'});
          assert.equal(await pending,false);
          assert.deepEqual(h.events,['channel','get','ask']);

          h=harness({permission:{status:'granted'}});
          let finishToken,tokenStarted;
          const entered=new Promise(resolve=>tokenStarted=resolve);
          h.Notifications.getExpoPushTokenAsync=()=>{h.events.push('token');tokenStarted();return new Promise(resolve=>finishToken=resolve)};
          const automatic=h.register('session');
          await entered;
          const retry=h.register('session',true);
          h.Notifications.getPermissionsAsync=async()=>{h.events.push('get-again');return {status:'denied',canAskAgain:false}};
          finishToken({data:'synthetic'});
          assert.equal(await automatic,true);
          assert.equal(await retry,'blocked');
          assert.deepEqual(h.events,['channel','get','project','token','post','channel','get-again']);

          h=harness({cached:'cached'});
          let finishFirst,firstStarted,checks=0;
          const firstCheck=new Promise(resolve=>firstStarted=resolve);
          h.Notifications.getPermissionsAsync=()=>{
            checks++;
            if(checks===1){firstStarted();return new Promise(resolve=>finishFirst=resolve)}
            return Promise.resolve({status:'granted'});
          };
          const first=h.register('session',true),second=h.register('session',true);
          await firstCheck;
          await Promise.resolve();
          assert.equal(checks,1);
          finishFirst({status:'granted'});
          assert.deepEqual(await Promise.all([first,second]),[true,true]);
          assert.equal(checks,2);
        })().catch(error=>{console.error(error);process.exitCode=1});
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")), json.dumps(registration))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                         "Node.js and mobile TypeScript are needed")
    def test_explicit_blocked_retry_offers_system_settings(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        callback = "async () => {" + mobile.split('{button("Enable activity alerts", async () => {', 1)[1].split(
            "\n        }, true)}", 1
        )[0] + "\n}"
        script = """
        const assert=require('node:assert/strict'),ts=require(%s),source=ts.transpile('const callback='+%s);
        async function run(result,changeSession=false) {
          const alerts=[],pushSessionRef={current:'session'},pushSessionGenerationRef={current:1};
          let opened=0;
          const registerPushToken=async()=>{if(changeSession)pushSessionGenerationRef.current++;return result};
          const Alert={alert:(...args)=>alerts.push(args)},Linking={openSettings:async()=>{opened++}};
          const callback=new Function('token','pushSessionRef','pushSessionGenerationRef','registerPushToken','Alert','Linking','fail','isTransientPushServiceUnavailable','pushRegistrationErrorMessage',
            source+';return callback')('session',pushSessionRef,pushSessionGenerationRef,registerPushToken,Alert,Linking,()=>{},()=>false,()=>{});
          await callback();
          return {alerts,getOpened:()=>opened};
        }
        (async()=>{
          const blocked=await run('blocked');
          assert.match(blocked.alerts[0][0],/blocked/i);
          const settings=blocked.alerts[0][2].find(button=>button.text==='Open settings');
          assert.ok(settings);settings.onPress();assert.equal(blocked.getOpened(),1);
          const denied=await run(false);assert.match(denied.alerts[0][0],/off/i);
          const granted=await run(true);assert.match(granted.alerts[0][0],/enabled/i);
          const stale=await run('blocked',true);assert.equal(stale.alerts.length,0);
        })().catch(error=>{console.error(error);process.exitCode=1});
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")), json.dumps(callback))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                         "Node.js and mobile TypeScript are needed")
    def test_only_service_unavailable_is_retried_a_bounded_number_of_times(self):
        source = (ROOT / "mobile" / "pushRegistration.ts").read_text(encoding="utf-8")
        script = """
        const assert = require('node:assert/strict');
        const ts = require(%s);
        const source = ts.transpile(%s, {module: ts.ModuleKind.CommonJS});
        const exports = {};
        new Function('exports', source)(exports);
        (async () => {
          let calls = 0, waits = [];
          const result = await exports.retryTransientPushOperation(async () => {
            calls++;
            if (calls < 3) throw Object.assign(new Error('Firebase unavailable'), {code:'SERVICE_NOT_AVAILABLE'});
            return 'token';
          }, async delay => waits.push(delay));
          assert.equal(result, 'token');
          assert.equal(calls, 3);
          assert.deepEqual(waits, [500, 1500]);

          calls = 0; waits = [];
          await assert.rejects(exports.retryTransientPushOperation(async () => {
            calls++;
            throw Object.assign(new Error('Firebase unavailable'), {code:'SERVICE_NOT_AVAILABLE'});
          }, async delay => waits.push(delay)), /Firebase unavailable/);
          assert.equal(calls, 3);
          assert.deepEqual(waits, [500, 1500]);

          calls = 0; waits = [];
          await assert.rejects(exports.retryTransientPushOperation(async () => {
            calls++;
            throw new Error('Permission denied');
          }, async delay => waits.push(delay)), /Permission denied/);
          assert.equal(calls, 1);
          assert.deepEqual(waits, []);
          assert.match(exports.pushRegistrationErrorMessage({code:'SERVICE_NOT_AVAILABLE'}), /Zorlii is still available/);
          assert.equal(exports.pushRegistrationErrorMessage(new Error('Permission denied')), 'Permission denied');
        })().catch(error => { console.error(error); process.exitCode = 1; });
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")), json.dumps(source))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_push_client_uses_the_bounded_retry_only_for_expo_token_acquisition(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('import { isTransientPushServiceUnavailable, pushRegistrationErrorMessage, retryTransientPushOperation } from "./pushRegistration";', mobile)
        self.assertIn("retryTransientPushOperation(() => {", mobile)
        self.assertIn("return Notifications.getExpoPushTokenAsync({ projectId })", mobile)
        self.assertIn("pushRetryPendingRef.current", mobile)
        self.assertIn("pushRetryPendingRef.current && !pushReturnRetryUsedRef.current", mobile)
        self.assertIn("pushReturnRetryUsedRef.current = true;", mobile)
        self.assertIn("Temporary notification service issue", mobile)
        self.assertIn("This device is registered for Zorlii activity alerts.", mobile)
        self.assertIn("state === \"active\"", mobile)
        self.assertNotIn("console.log(expoToken)", mobile)
        self.assertIn('setError(current => current === pushRegistrationErrorMessage({ code: "SERVICE_NOT_AVAILABLE" }) ? "" : current)', mobile)

    @unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                         "Node.js and mobile TypeScript are needed")
    def test_registration_does_not_publish_or_cache_for_an_ended_session(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        registration = "async function registerPushToken" + mobile.split("async function registerPushToken", 1)[1].split(
            "\n  async function loadFeed", 1
        )[0]
        script = """
        const assert=require('node:assert/strict'),ts=require(%s);
        const code=ts.transpile(%s);
        const refs={pushSessionRef:{current:'old'},pushSessionGenerationRef:{current:1},pushTokenRef:{current:null},pushRegistrationPromiseRef:{current:null},
          pushRegistrationOwnerRef:{current:''},pushRegistrationGenerationRef:{current:0},pushPostingRef:{current:false},
          pushRetryPendingRef:{current:false},pushReturnRetryUsedRef:{current:false}};
        let release, entered, calls=[];
        const tokenWait=new Promise(resolve=>release=resolve);
        const tokenEntered=new Promise(resolve=>entered=resolve);
        const Notifications={AndroidImportance:{HIGH:1},setNotificationChannelAsync:async()=>{},
          getPermissionsAsync:async()=>({status:'granted'}),
          getExpoPushTokenAsync:async()=>{entered(); return tokenWait;}};
        const Platform={OS:'android'},Device={isDevice:true},Constants={easConfig:{projectId:'test'}};
        const canRegisterPushToken=()=>true,isTransientPushServiceUnavailable=()=>false,
          retryTransientPushOperation=operation=>operation(),API_URL='http://local.test';
        let fetch=async (url,options)=>{calls.push(options.method); return {ok:true};};
        const register=new Function(...Object.keys(refs),'Notifications','Platform','Device','Constants',
          'canRegisterPushToken','isTransientPushServiceUnavailable','retryTransientPushOperation','API_URL','fetch','warnPushCleanup',
          code+';return registerPushToken;')(...Object.values(refs),Notifications,Platform,Device,Constants,
          canRegisterPushToken,isTransientPushServiceUnavailable,retryTransientPushOperation,API_URL,(...args)=>fetch(...args),
          ()=>{throw Error('Unexpected cleanup warning')});
        (async()=>{
          const pending=register('old');
          await tokenEntered;
          refs.pushSessionRef.current='new';
          release({data:'synthetic'});
          assert.equal(await pending,false);
          assert.deepEqual(calls,[]);
          assert.equal(refs.pushTokenRef.current,null);
          let finishPost, postStarted;
          const waitingPost=new Promise(resolve=>finishPost=resolve);
          const started=new Promise(resolve=>postStarted=resolve);
          fetch=async (url,options)=>{
            const who=options.headers.Authorization;
            calls.push([options.method,who]);
            if(options.method==='POST' && who==='Bearer old'){postStarted();await waitingPost;}
            return {ok:true};
          };
          refs.pushSessionRef.current='old';
          const oldRegistration=register('old');
          await started;
          refs.pushSessionRef.current='new';
          const newRegistration=register('new');
          finishPost();
          assert.equal(await oldRegistration,false);
          assert.equal(await newRegistration,true);
          assert.deepEqual(calls,[['POST','Bearer old'],['DELETE','Bearer old'],['POST','Bearer new']]);
          assert.equal(refs.pushTokenRef.current,'synthetic');
        })().catch(error=>{console.error(error);process.exitCode=1});
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")), json.dumps(registration))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node") and (ROOT / "mobile" / "node_modules" / "typescript").is_dir(),
                         "Node.js and mobile TypeScript are needed")
    def test_logout_warns_safely_on_stale_cleanup_failures_and_completes(self):
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        registration = "function warnPushCleanup" + mobile.split("function warnPushCleanup", 1)[1].split(
            "\n  async function loadFeed", 1
        )[0]
        logout = "async function logout()" + mobile.split("async function logout()", 1)[1].split(
            "\n  async function exportAccount", 1
        )[0]
        script = """
        const assert=require('node:assert/strict'),ts=require(%s);
        const code=ts.transpile(%s + '\\n' + %s);
        async function run(outcome) {
          const refs={pushSessionRef:{current:'old'},pushSessionGenerationRef:{current:1},pushTokenRef:{current:null},pushRegistrationPromiseRef:{current:null},
            pushRegistrationOwnerRef:{current:''},pushRegistrationGenerationRef:{current:0},pushPostingRef:{current:false},
            pushRetryPendingRef:{current:false},pushReturnRetryUsedRef:{current:false}};
          let startPost, finishPost, warnings=[], loggedOut=false, cleared=false, screen='';
          const started=new Promise(resolve=>startPost=resolve);
          const pendingPost=new Promise(resolve=>finishPost=resolve);
          const deps={
            Alert:{alert:(...args)=>warnings.push(args)},
            Notifications:{AndroidImportance:{HIGH:1},setNotificationChannelAsync:async()=>{},
              getPermissionsAsync:async()=>({status:'granted'}),getExpoPushTokenAsync:async()=>({data:'synthetic-secret-token'})},
            Platform:{OS:'android'},Device:{isDevice:true},Constants:{easConfig:{projectId:'test'}},
            canRegisterPushToken:()=>true,isTransientPushServiceUnavailable:()=>false,retryTransientPushOperation:op=>op(),
            API_URL:'http://local.test',
            fetch:async(url,options)=>{
              if(options.method==='POST') { startPost(); await pendingPost; return {ok:true}; }
              if(outcome==='network') throw new Error('synthetic-secret-token');
              return {ok:outcome==='ok'};
            },
            request:async(path)=>{if(path==='/api/auth/logout')loggedOut=true;},
            SecureStore:{deleteItemAsync:async()=>{cleared=true}},resetConversationState:()=>{},
            setToken:()=>{},updateMe:()=>{},setScreen:s=>{screen=s},setForm:()=>{},setPostMedia:()=>{},fail:()=>{},
            setTimeout:outcome==='timeout'?callback=>{queueMicrotask(callback);return 1}:setTimeout,
            clearTimeout:outcome==='timeout'?()=>{}:clearTimeout
          };
          const fn=new Function(...Object.keys(refs),...Object.keys(deps),code+';return {registerPushToken,logout};');
          const app=fn(...Object.values(refs),...Object.values(deps));
          let registration;
          if(outcome==='unexpected' || outcome==='timeout') {
            refs.pushPostingRef.current=true;
            refs.pushRegistrationPromiseRef.current=outcome==='timeout'?new Promise(()=>{}):Promise.reject(new Error('synthetic-secret-token'));
          } else {
            registration=app.registerPushToken('old');
            await started;
          }
          const logout=app.logout();
          if(finishPost) finishPost();
          await Promise.all([registration,logout]);
          assert.equal(loggedOut,true); assert.equal(cleared,true); assert.equal(screen,'login');
          assert.equal(refs.pushTokenRef.current,null);
          assert.equal(warnings.length,outcome==='ok'?0:1);
          assert.equal(JSON.stringify(warnings).includes('synthetic-secret-token'),false);
          if(warnings.length) assert.match(warnings[0][1],/couldn't confirm/i);
        }
        (async()=>{for(const outcome of ['http','network','unexpected','timeout','ok']) await run(outcome)})()
          .catch(error=>{console.error(error);process.exitCode=1});
        """ % (json.dumps(str(ROOT / "mobile" / "node_modules" / "typescript")), json.dumps(registration), json.dumps(logout))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
