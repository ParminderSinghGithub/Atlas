import { createClient } from "redis";
const redisClient = createClient({ url: "redis://redis:6379" });
await redisClient.connect();
export default redisClient;
