import {useRef,useState} from 'react';

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
export default function CameraCapture({onPhoto,disabled=false,cameraOnly=false,label='手機拍照'}:{onPhoto:(photo:string)=>void;disabled?:boolean;cameraOnly?:boolean;label?:string}){
 const camera=useRef<HTMLInputElement>(null),album=useRef<HTMLInputElement>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 async function select(input:HTMLInputElement){
  const file=input.files?.[0];input.value='';if(!file)return;
  setBusy(true);setError('');
  try{onPhoto(await preparePhoto(file));}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}
 }
 return <div className="space-y-1">
  <input hidden ref={camera} type="file" accept="image/*" capture="environment" onChange={e=>void select(e.currentTarget)}/>
  {!cameraOnly&&<input hidden ref={album} type="file" accept="image/*" onChange={e=>void select(e.currentTarget)}/>}
  <div className="flex flex-wrap gap-2">
   <button type="button" className="secondary" disabled={disabled||busy} onClick={()=>camera.current?.click()}>{busy?'處理照片…':label}</button>
   {!cameraOnly&&<button type="button" className="secondary" disabled={disabled||busy} onClick={()=>album.current?.click()}>選擇相簿</button>}
  </div>
  {error&&<p role="alert" className="text-red-700">{error}</p>}
 </div>;
}
