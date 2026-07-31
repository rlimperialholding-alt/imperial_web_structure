import { count } from "drizzle-orm";
import { leads, tasks } from "@/db/schema";
import { getDb } from "@/db";

const seedLeads = [
  { name:"Minta Anna", title:"120 m²-es Danish Fabrik családi ház", brand:"Danish Fabrik", brandCode:"DF", location:"Üröm", email:"anna@example.hu", phone:"+36 30 111 2233", source:"Google Ads", owner:"Kiss Andrea", ownerInitials:"KA", stage:"offer" as const, value:118000000, probability:55, score:91, quality:94, temperature:"hot" as const, health:"green" as const, nextAction:"Helyszíni felmérés egyeztetése", nextDate:"Ma, 14:30", projectType:"Családi ház", technology:"Danish Fabrik", plot:true, financing:true, notes:"Otthon Start finanszírozásban gondolkodik. A telek rendelkezésre áll." },
  { name:"Nagy Péter", title:"Váci kétlakásos Prefab projekt", brand:"Prefab", brandCode:"PF", location:"Vác", email:"peter@nagyprojekt.hu", phone:"+36 20 222 3344", source:"Ajánlás", owner:"Kiss Andrea", ownerInitials:"KA", stage:"negotiation" as const, value:180000000, probability:72, score:94, quality:98, temperature:"hot" as const, health:"yellow" as const, nextAction:"Döntési akadályok átbeszélése", nextDate:"Ma, 11:00", projectType:"Kétlakásos ház", technology:"Prefab / Leier", plot:true, financing:true, notes:"Ajánlat kiküldve. A döntéshez a műszaki tartalom véglegesítése szükséges." },
  { name:"Kovács Dóra", title:"Gödi 90 m²-es családi ház", brand:"BauFreund", brandCode:"BF", location:"Göd", email:"dora@example.hu", phone:"—", source:"Facebook", owner:"Farkas Bence", ownerInitials:"FB", stage:"new" as const, value:72000000, probability:18, score:62, quality:54, temperature:"cold" as const, health:"red" as const, nextAction:"Első visszahívás", nextDate:"3 órája lejárt", projectType:"Családi ház", technology:"Tégla", plot:false, financing:false, notes:"A telekválasztás még folyamatban van. Költségkeret pontosítandó." },
  { name:"Szabó Márton", title:"Passzát típusház Érden", brand:"Imperial", brandCode:"IH", location:"Érd", email:"marton@example.hu", phone:"+36 70 444 5566", source:"Weboldal", owner:"Kiss Andrea", ownerInitials:"KA", stage:"consultation" as const, value:96000000, probability:42, score:83, quality:86, temperature:"warm" as const, health:"green" as const, nextAction:"Konzultáció összefoglaló küldése", nextDate:"Holnap, 09:00", projectType:"Családi ház", technology:"Tégla", plot:true, financing:true, notes:"Passzát típusház, kisebb alaprajzi módosításokkal." },
  { name:"Tóth Katalin", title:"Telek és 3 hálós Eco Basic", brand:"Danish Fabrik", brandCode:"DF", location:"Dunakeszi", email:"katalin@example.hu", phone:"+36 30 555 6677", source:"Kiállítás", owner:"Farkas Bence", ownerInitials:"FB", stage:"contact" as const, value:83000000, probability:28, score:71, quality:78, temperature:"warm" as const, health:"yellow" as const, nextAction:"Finanszírozási igény egyeztetése", nextDate:"július 21.", projectType:"Családi ház", technology:"Danish Fabrik", plot:true, financing:false, notes:"Három hálószoba, gyors beköltözés elsődleges." },
  { name:"Varga Építő Kft.", title:"12 lakásos szerkezetépítési csomag", brand:"Bautica", brandCode:"BA", location:"Budapest XI.", email:"projekt@vargaepito.hu", phone:"+36 1 555 0199", source:"Baudata", owner:"Kiss Andrea", ownerInitials:"KA", stage:"offer" as const, value:265000000, probability:48, score:86, quality:91, temperature:"hot" as const, health:"green" as const, nextAction:"Műszaki ajánlat jóváhagyása", nextDate:"július 22.", projectType:"B2B kivitelezés", technology:"Vasbeton", plot:true, financing:true, notes:"B2B opportunity. Minimum árrés ellenőrzés kötelező." },
  { name:"Horváth Gábor", title:"110 m²-es Imperial típusház", brand:"Imperial", brandCode:"IH", location:"Győr", email:"gabor@example.hu", phone:"+36 30 772 1144", source:"Google organikus", owner:"Farkas Bence", ownerInitials:"FB", stage:"contract" as const, value:103000000, probability:92, score:96, quality:97, temperature:"hot" as const, health:"green" as const, nextAction:"Szerződéstervezet jóváhagyása", nextDate:"július 20.", projectType:"Családi ház", technology:"Tégla", plot:true, financing:true, notes:"Szerződés előkészítés alatt. Kiküldés emberi jóváhagyáshoz kötött." },
  { name:"Molnár Eszter", title:"Pajtaház a Velencei-tónál", brand:"Prefab", brandCode:"PF", location:"Pákozd", email:"eszter@example.hu", phone:"+36 20 883 4466", source:"Instagram", owner:"Kiss Andrea", ownerInitials:"KA", stage:"contact" as const, value:126000000, probability:32, score:76, quality:68, temperature:"warm" as const, health:"yellow" as const, nextAction:"Telekadatok bekérése", nextDate:"július 23.", projectType:"Pajtaház", technology:"Liapor", plot:true, financing:false, notes:"Modern pajtaház, nagy üvegfelületekkel." },
];

const seedTasks = [
  { title:"Kovács Dóra első visszahívása", leadId:3, leadName:"Kovács Dóra", type:"Hívás", due:"3 órája lejárt", priority:"critical" as const, ai:true },
  { title:"Nagy Péter ajánlat utánkövetése", leadId:2, leadName:"Nagy Péter", type:"Follow-up", due:"Ma, 11:00", priority:"high" as const, ai:true },
  { title:"Minta Anna helyszíni felmérés egyeztetése", leadId:1, leadName:"Minta Anna", type:"Találkozó", due:"Ma, 14:30", priority:"normal" as const, ai:false },
  { title:"Varga Építő műszaki ajánlat belső kontrollja", leadId:6, leadName:"Varga Építő Kft.", type:"Jóváhagyás", due:"Ma, 16:00", priority:"high" as const, ai:true },
];

export async function seedCrmIfEmpty(ownerEmail: string) {
  if (process.env.CRM_DEMO_SEED_ENABLED !== "true") return;
  const db = await getDb();
  const [{ total }] = await db.select({ total: count() }).from(leads);
  if (total > 0) return;
  const now = new Date().toISOString();
  await db.insert(leads).values(seedLeads.map((lead) => ({ ...lead, createdAt: now, updatedAt: now })));
  await db.insert(tasks).values(seedTasks.map((task) => ({ ...task, done:false, ownerEmail, createdAt: now, updatedAt: now })));
}
