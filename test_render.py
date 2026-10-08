import os, json, subprocess, tempfile
os.environ['RENDER_TOKEN']='testtoken'; os.environ['OUT_DIR']=tempfile.mkdtemp(); os.environ['BRAND']='Vorvia Media'
import app as A
c=A.app.test_client(); H={'Authorization':'Bearer testtoken'}
ok=bad=0
def t(cond,msg):
    global ok,bad; ok+=cond; bad+=(not cond); print(('PASS ' if cond else 'FAIL ')+msg)
t(c.get('/health').json['ok'],'health')
t(c.post('/render',json={}).status_code==401,'no token -> 401')
t(c.post('/render',json={},headers={'Authorization':'Bearer wrong'}).status_code==401,'wrong token -> 401')
llm_text = 'Here is the package...\nRENDER_SPEC:\n```json\n{"width":540,"height":960,"fps":15,"scenes":[{"text":"Seal air leaks","voiceover":"Sealing air leaks around doors and windows can cut heating and cooling waste.","duration":3},{"text":"Use LED bulbs","voiceover":"Switching to LED bulbs uses far less energy for the same light."},{"text":"Follow Vorvia Media","voiceover":"Practical energy tips for your home."}]}\n```\nnotes'
r=c.post('/render',json={'jobId':'J1','taskType':'VIDEO','renderSpec':llm_text},headers=H); j=r.json
print(json.dumps(j,indent=1))
t(r.status_code==200 and j['status']=='COMPLETED' and j['verified'] is True,'render completed + verified')
t(j['music'] is False,'no music flag')
rid=j['renderId']; f=c.get('/files/%s.mp4'%rid,headers=H)
t(f.status_code==200 and len(f.data)==j['bytes'],'download matches reported size')
t(c.get('/files/%s.mp4'%rid).status_code==401,'download needs token')
p=os.path.join(os.environ['OUT_DIR'],rid+'.mp4')
streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',p]))['streams']
t({'video','audio'}<={s['codec_type'] for s in streams},'ffprobe: video+audio streams')
vs=[s for s in streams if s['codec_type']=='video'][0]; t((vs['width'],vs['height'])==(540,960),'resolution 540x960')
# audio actually non-silent
vol=subprocess.run(['ffmpeg','-i',p,'-af','volumedetect','-f','null','-'],capture_output=True,text=True).stderr
mv=[l for l in vol.splitlines() if 'max_volume' in l]; print(mv)
t(mv and float(mv[0].split('max_volume:')[1].split('dB')[0])>-40,'audio is not silent (TTS worked)')
t(c.post('/render',json={'renderSpec':'no json here'},headers=H).status_code==422,'garbage spec -> 422')
t(c.post('/render',json={'renderSpec':{'scenes':[{'text':'x'*900}]}},headers=H).status_code==422,'oversized scene -> 422')
t(c.post('/render',json={'renderSpec':{'scenes':[{'text':'a','voiceover':'b'}]*20}},headers=H).status_code==422,'too many scenes -> 422')
t(c.post('/render',json={'renderSpec':{'width':5000,'scenes':[{'text':'a'}]}},headers=H).status_code==422,'bad resolution -> 422')
t(c.get('/files/..%2Fetc.mp4',headers=H).status_code in (404,),'path traversal blocked')
print('%d passed, %d failed'%(ok,bad))
