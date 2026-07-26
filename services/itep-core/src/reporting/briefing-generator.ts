import type {ExecutiveBriefing,ExecutiveMetrics} from "./types.js";
export class ExecutiveBriefingGenerator{
 generate({kind,generatedAt,metrics:m}:{kind:"DAILY"|"WEEKLY"|"MONTHLY";generatedAt:Date;metrics:ExecutiveMetrics}):ExecutiveBriefing{
  const risks:string[]=[],actions:string[]=[],queue:string[]=[];
  if(m.criticalOpenTasks){risks.push(`${m.criticalOpenTasks} nyitott P1 feladat azonnali figyelmet igényel.`);actions.push("A nyitott P1 feladatokat vezetői szinten még ma át kell tekinteni.");queue.push(`${m.criticalOpenTasks} P1 feladat státuszának ellenőrzése.`)}
  if(m.criticalIncidents){risks.push(`${m.criticalIncidents} kritikus Human Anne-incidens nyitott.`);actions.push("A kritikus incidensekhez felelőst és határidőt kell rendelni.");queue.push(`${m.criticalIncidents} kritikus incidens felülvizsgálata.`)}
  if(m.overdueTasks){risks.push(`${m.overdueTasks} feladat lejárt és nincs lezárva.`);actions.push("A lejárt feladatoknál okkódot, új határidőt és bizonyítékot kell rögzíteni.")}
  const r=m.highestRiskAssignees[0];if(r?.overdueOpen)risks.push(`Legnagyobb végrehajtási kockázat: ${r.assigneeId}, ${r.overdueOpen} lejárt feladattal.`);
  if(m.recurringIncidentCategories[0]?.count>=3)actions.push(`Folyamatjavítás szükséges a(z) ${m.recurringIncidentCategories[0].category} kategóriában.`);
  for(const a of m.highestRiskAssignees.slice(0,3))if(a.overdueOpen)queue.push(`${a.assigneeId}: ${a.overdueOpen} lejárt feladat áttekintése.`);
  if(!risks.length)risks.push("Nincs azonosított kritikus végrehajtási kockázat.");if(!actions.length)actions.push("A jelenlegi végrehajtási rend fenntartása javasolt.");
  const best=m.topPerformers[0];
  return{title:kind==="DAILY"?"Digital Anne – napi vezetői briefing":kind==="WEEKLY"?"Digital Anne – heti vezetői riport":"Digital Anne – havi vezetői riport",generatedAt,periodLabel:`${m.window.from.toISOString()} – ${m.window.to.toISOString()}`,summary:`${m.totalTasks} aktív feladatból ${m.closedTasks} lezárult, ${m.overdueTasks} lejárt. Teljesítési arány: ${m.completionRate}%, SLA: ${m.slaRate}%. Nyitott P1: ${m.criticalOpenTasks}, kritikus incidens: ${m.criticalIncidents}.`,highlights:best?[`Legjobb teljesítő: ${best.assigneeId}, ${best.completionRate}% teljesítési aránnyal.`]:["Nincs elegendő adat teljesítményi kiemeléshez."],risks,recommendedActions:actions,humanAnneQueue:queue,metrics:m}
 }
}
