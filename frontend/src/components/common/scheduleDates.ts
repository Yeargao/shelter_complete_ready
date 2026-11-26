
export function taipeiToday() {
 return new Intl.DateTimeFormat('fr-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
}
export function addDays(day:string, offset:number) {
 const date = new Date(day+'T00:00:00Z');
 date.setUTCDate(date.getUTCDate()+offset);
 return date.toISOString().slice(0,10);
}
export function gridTime(quarter:number) {
 return String(Math.floor(quarter/4)).padStart(2,'0')+':'+String(quarter%4*15).padStart(2,'0');
}
export function timeGrid(time:string|null) {
 if(!time)return 0;
 const [h,m]=time.split(':').map(Number);
 return h*4+m/15;
}

export const lunchBreak = [46,54] as const;
