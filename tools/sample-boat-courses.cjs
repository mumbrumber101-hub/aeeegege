const fs=require('fs'),vm=require('vm');
const path=require('path'),root=path.resolve(__dirname,'..');
const map=fs.readFileSync(path.join(root,'map-source.html'),'utf8');
const DATA=JSON.parse(map.match(/const DATA = (.*);/)[1]);
const source=JSON.parse(fs.readFileSync(path.join(root,'animation-bundle.json'))).js;
const stub=()=>({appendChild(){},setAttribute(){},style:{}});
const context={WATER_NAVIGATION:fs.existsSync(path.join(root,'water-navigation.json'))?JSON.parse(fs.readFileSync(path.join(root,'water-navigation.json'))):{},DATA,SHEETS:{quad:{w:4145,h:5706},vicinity:{w:3314,h:4191}},placeById:Object.fromEntries(DATA.places.map(p=>[p.id,p])),document:{getElementById:stub,createElement:stub},viewer:stub(),window:{},console};
vm.createContext(context);
vm.runInContext(source.slice(0,source.indexOf("  ui('ap-sequence').innerHTML")).replace(/\/\* Water navigation start \*\/[\s\S]*?\/\* Water navigation end \*\//g,match=>process.argv.includes('--corrected')?match:'')+`window.audit={sequences,modelFor,trackPose};})();`,context);
let results=[];
for(const sequence of context.window.audit.sequences){
 for(const scene of sequence.stages){
  const m=context.window.audit.modelFor(scene);
  for(const track of m.actors){
   if(!['raft','boat'].includes(track.actor.type))continue;
   const times=[...new Set([...Array.from({length:201},(_,i)=>i/200),...(track.frames||[]).map(f=>f.t)])].sort((a,b)=>a-b);
   results.push({sequence:sequence.id,scene:scene.id,actor:track.id,frames:track.frames,points:times.map(t=>({t,...context.window.audit.trackPose(track,t,m,!process.argv.includes('--heading'))}))});
  }
 }
}
fs.writeFileSync(process.argv[2]||'/tmp/reef-courses.json',JSON.stringify(results));
console.log('sampled',results.length,'boat tracks');
