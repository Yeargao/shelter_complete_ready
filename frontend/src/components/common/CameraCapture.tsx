import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';

// Re-encode on the client to limit transfer size and remove EXIF metadata.
export async function preparePhoto(file:File):Promise<string>{
 if(file.size>25*1024*1024)throw Error('原始照片最多 25 MB');
 const url=URL.createObjectURL(file);
 try{
  const image=new Image();
  await new Promise<void>((resolve,reject)=>{image.onload=()=>resolve();image.onerror=()=>reject(Error('無法讀取圖片，請使用 JPEG、PNG 或 WebP'));image.src=url;});
  const scale=Math.min(1,1280/Math.max(image.naturalWidth,image.naturalHeight));
  const canvas=document.createElement('canvas');
  canvas.width=Math.max(1,Math.round(image.naturalWidth*scale));canvas.height=Math.max(1,Math.round(image.naturalHeight*scale));
  const ctx=canvas.getContext('2d');if(!ctx)throw Error('無法處理照片');
  ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0,canvas.width,canvas.height);
  const data=canvas.toDataURL('image/jpeg',.82);
  if(!data.startsWith('data:image/jpeg;base64,')||data.length>700000)throw Error('照片壓縮後仍過大，請重新拍攝');
  return data;
 }finally{URL.revokeObjectURL(url);}
}
// Convert a normalized photo back into a File for older report/comparison flows.
export function photoFile(data:string):File{
 const bytes=atob(data.split(',')[1]),buffer=new Uint8Array(bytes.length);
 for(let i=0;i<bytes.length;i++)buffer[i]=bytes.charCodeAt(i);
 return new File([buffer],'photo-'+Date.now()+'.jpg',{type:'image/jpeg'});
}

function cameraError(e:unknown):string{
 const name=e instanceof Error?e.name:'';
 if(name==='NotAllowedError'||name==='SecurityError')return '相機權限未允許，請在瀏覽器網站設定允許相機後重試。';
 if(name==='NotFoundError'||name==='OverconstrainedError')return '找不到可用相機，請確認裝置有相機。';
 if(name==='NotReadableError'||name==='AbortError')return '相機無法啟動，可能被其他 App 使用，請關閉後重試。';
 return '無法開啟相機，請重試或使用備用拍照方式。';
}
export default function CameraCapture({onPhoto,disabled=false,cameraOnly=false,label='手機拍照'}:{onPhoto:(photo:string)=>void;disabled?:boolean;cameraOnly?:boolean;label?:string}){
 const camera=useRef<HTMLInputElement>(null),album=useRef<HTMLInputElement>(null),video=useRef<HTMLVideoElement>(null);
 const stream=useRef<MediaStream|null>(null),generation=useRef(0),alive=useRef(true);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const [open,setOpen]=useState(false),[starting,setStarting]=useState(false),[ready,setReady]=useState(false);
 const [activeStream,setActiveStream]=useState<MediaStream|null>(null),[cameraMessage,setCameraMessage]=useState('');
 function stopTracks(){generation.current++;stream.current?.getTracks().forEach(track=>track.stop());stream.current=null;}
 function close(){stopTracks();setActiveStream(null);setOpen(false);setStarting(false);setReady(false);setCameraMessage('');}
 useEffect(()=>{alive.current=true;const pagehide=()=>{stopTracks();setActiveStream(null);setOpen(false);setStarting(false);setReady(false);};
  window.addEventListener('pagehide',pagehide);
  return()=>{alive.current=false;stopTracks();window.removeEventListener('pagehide',pagehide);};
 },[]);
 useEffect(()=>{if(!open||!activeStream||!video.current)return;
  const element=video.current;element.srcObject=activeStream;
  let valid=true;
  void element.play().catch(()=>{if(valid){setCameraMessage('相機畫面無法播放，請重新開啟相機。');setReady(false);}});
  return()=>{valid=false;element.srcObject=null;};
 },[open,activeStream]);
 useEffect(()=>{if(!open)return;const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();}};window.addEventListener('keydown',key,true);return()=>window.removeEventListener('keydown',key,true);},[open]);
 async function startCamera(){
  stopTracks();const id=generation.current;
  setError('');setCameraMessage('');setReady(false);setActiveStream(null);setOpen(true);setStarting(true);
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){
   setCameraMessage('即時相機需要 HTTPS 與支援相機的瀏覽器。請使用正式 HTTPS 網站，或使用下方備用拍照。');setStarting(false);return;
  }
  try{
   const next=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:'environment'},width:{ideal:1280},height:{ideal:960}}});
   if(!alive.current||generation.current!==id){next.getTracks().forEach(track=>track.stop());return;}
   stream.current=next;setActiveStream(next);setStarting(false);
  }catch(e){
   if(!alive.current||generation.current!==id)return;
   setCameraMessage(cameraError(e));setStarting(false);
  }
 }
 function takePhoto(){
  const frame=video.current;if(!frame||!frame.videoWidth||!frame.videoHeight||!ready)return;
  try{
   const scale=Math.min(1,1280/Math.max(frame.videoWidth,frame.videoHeight));
   const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(frame.videoWidth*scale));canvas.height=Math.max(1,Math.round(frame.videoHeight*scale));
   const ctx=canvas.getContext('2d');if(!ctx)throw Error('無法處理照片');
   ctx.drawImage(frame,0,0,canvas.width,canvas.height);
   const data=canvas.toDataURL('image/jpeg',.82);
   if(!data.startsWith('data:image/jpeg;base64,')||data.length>700000)throw Error('照片過大，請重新拍攝');
   close();onPhoto(data);
  }catch(e){setCameraMessage(e instanceof Error?e.message:String(e));}
 }
 async function select(input:HTMLInputElement){
  const file=input.files?.[0];input.value='';if(!file)return;
  setBusy(true);setError('');
  try{const data=await preparePhoto(file);if(alive.current)onPhoto(data);}catch(e){if(alive.current)setError(e instanceof Error?e.message:String(e));}finally{if(alive.current)setBusy(false);}
 }
 return <div className="space-y-1">
  <input hidden style={{display:'none'}} ref={camera} type="file" accept="image/*" capture="environment" onChange={e=>void select(e.currentTarget)}/>
  {!cameraOnly&&<input hidden style={{display:'none'}} ref={album} type="file" accept="image/*" onChange={e=>void select(e.currentTarget)}/>}
  <div className="flex flex-wrap gap-2">
   <button type="button" className="secondary" disabled={disabled||busy||open} onClick={()=>void startCamera()}>{busy?'處理照片…':label}</button>
   {!cameraOnly&&<button type="button" className="secondary" disabled={disabled||busy||open} onClick={()=>album.current?.click()}>選擇相簿</button>}
  </div>
  {error&&<p role="alert" className="text-red-700">{error}</p>}
  {open&&createPortal(<div role="presentation" style={{position:'fixed',inset:0,zIndex:2000,background:'rgba(0,0,0,.72)',display:'flex',alignItems:'center',justifyContent:'center',padding:12}}>
   <section role="dialog" aria-modal="true" aria-label="手機相機" className="panel space-y-3" style={{width:'min(100%,520px)',maxHeight:'92dvh',overflowY:'auto'}}>
    <h2>手機相機</h2>
    {starting&&<p role="status">正在開啟相機，請允許相機權限…</p>}
    {activeStream&&<video ref={video} autoPlay playsInline muted onPlaying={()=>setReady(true)} onLoadedData={()=>setReady(true)} style={{width:'100%',maxHeight:'60dvh',objectFit:'contain',background:'#111',borderRadius:10}}/>}
    {cameraMessage&&<p role="alert" className="text-red-700">{cameraMessage}</p>}
    <div className="flex flex-wrap gap-2">
     {activeStream&&<button type="button" disabled={!ready||disabled} onClick={takePhoto}>拍攝照片</button>}
     {!starting&&cameraMessage&&<><button type="button" className="secondary" onClick={()=>void startCamera()}>重新開啟相機</button><button type="button" className="secondary" onClick={()=>{close();camera.current?.click();}}>備用拍照（系統相機）</button></>}
     <button type="button" className="secondary" onClick={close}>取消拍照</button>
    </div>
   </section>
  </div>,document.body)}
 </div>;
}
