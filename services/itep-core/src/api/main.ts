import { buildServer } from "./server.js";
import { loadConfig } from "../config/env.js";
const config = loadConfig();
const app = await buildServer();
app.listen({ port: config.PORT, host: config.HOST }).catch((error) => {
  app.log.error(error); process.exit(1);
});
