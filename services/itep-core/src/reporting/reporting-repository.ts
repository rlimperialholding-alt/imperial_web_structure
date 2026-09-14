import type {IncidentSnapshot,ReportingTaskSnapshot,ReportingWindow} from "./types.js";
export interface ReportingRepository{loadTasks(window:ReportingWindow):Promise<ReportingTaskSnapshot[]>;loadIncidents(window:ReportingWindow):Promise<IncidentSnapshot[]>}
