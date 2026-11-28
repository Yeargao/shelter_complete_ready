import {useEffect,useRef,useState,type SetStateAction} from 'react';
const base=(import.meta.env.VITE_API_URL||'').replace(/\/+$/,'');
const prefix='shelter-smart-v1:';
export function useStored<T>(name:string,initial:T){
 const key=prefix+name;
 const [value,setValue]=useState<T>(()=>{try{const raw=sessionStorage.getItem(key);return raw===null?initial:JSON.parse(raw) as T}catch{return initial}});
 const ref=useRef(value);
 useEffect(()=>{const sync=(e:Event)=>{if((e as CustomEvent<string>).detail!==key)return;try{const raw=sessionStorage.getItem(key);const next=raw===null?initial:JSON.parse(raw) as T;ref.current=next;setValue(next)}catch{}};window.addEventListener('shelter-smart-update',sync);return()=>window.removeEventListener('shelter-smart-update',sync)},[key]);
 const owner=useRef(sessionStorage.getItem('shelter_token'));
 function update(next:SetStateAction<T>){
  if(owner.current!==sessionStorage.getItem('shelter_token'))return;
  const value=typeof next==='function'?(next as (v:T)=>T)(ref.current):next;
  ref.current=value;setValue(value);
  try{sessionStorage.setItem(key,JSON.stringify(value)??'null');window.dispatchEvent(new CustomEvent('shelter-smart-update',{detail:key}))}catch{/* result remains in memory */}
 }
 return [value,update] as const;
}
export async function smartRequest<T>(path:string,body?:object,method?:string):Promise<T>{
 const response=await fetch(base+'/api/smart'+path,{method:method??(body?'POST':'GET'),cache:'no-store',headers:{'Content-Type':'application/json',Authorization:'Bearer '+sessionStorage.getItem('shelter_token')},...(body?{body:JSON.stringify(body)}:{})});
 const data=await response.json();
 if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail??'請求失敗'));
 return data as T;
}

export const metrics={stock:'飼料庫存低於（公斤）',stay:'在所超過（天）且健康待確認',overdue:'緊急任務逾期',load:'今日排定工時達（%）',vaccine:'疫苗即將到期（天）'};
export const events={intake:'動物入所',sick:'生病',injured:'受傷',serious:'嚴重健康異常'};
export const labels=['健康狀態待確認','優先確認健康狀況','確認疫苗紀錄','確認驅蟲紀錄','健康問題追蹤'];
export type Metric=keyof typeof metrics;
export type EventKind=keyof typeof events;
export type ReportKind='health'|'species'|'tasks'|'staff'|'intake';
export type Command={type:'rule';metric:Metric;threshold:number}|{type:'report';kind:ReportKind;start:string;end:string}|{type:'link';path:string;message:string}|{type:'clarify';message:string}|{type:'task';animal_id:number;label:string;earliest:string;due:string;name:string}|{type:'workflow';event:EventKind;labels:string[]};
export type Report={title:string;rows:{label:string;value:number;total?:number;completed?:number}[];note:string;start:string;end:string;unit:string};
export type Option={id:number;name:string};
export type Options={animals:Option[];staff:Option[];labels:string[]};
export type Rule={id:string;metric:Metric;threshold:number};
export type Workflow={id:string;event:EventKind;labels:string;cursor:number};
export type Inbox={id:string;kind:string;detail:string;created:string;state:string};
export type Monitor={rules:Rule[];workflows:Workflow[];inbox:Inbox[];history:Inbox[]};
export type Check={ok:boolean;issues:string[];note:string};
export type Handover={name:string;day:string;done:number;pending:number;tasks:{task_id:string;name:string;label:string;state:string;result:string|null;note:string|null}[];issues:{task_id:string;name:string;note:string}[]};
export function isSmartCommand(text:string){return /提醒|通知|統計|報表|分布|完成率|開啟|前往|我要(?:修改|編輯|新增|處理|看)|工作流程|自動化流程|(?:新增|建立|安排|加一個|加一項).*任務/.test(text)}
export function splitCommands(text:string){return text.split(/[；;\n]+|(?:，|,)\s*(?=並|再|另外)|(?:並且|並)(?=幫|安排|新增|建立|統計|開啟)/).map(s=>s.trim().replace(/^(並且|並|再|另外)/,'')).filter(Boolean)}
export async function executeCommand(command:Command){
 if(command.type==='rule'||command.type==='workflow')throw Error('此功能已移除');
 if(command.type==='task'){const r=await smartRequest<{message:string}>('/task',{animal_id:command.animal_id,label:command.label,earliest:command.earliest,due:command.due});return r.message}
 throw Error('此操作無法執行');
}
