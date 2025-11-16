import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import authRoutes from "./routes/auth.js";
import sequelize from "./db/config.js";
import User from "./models/User.js";

// Load environment variables first
dotenv.config();

const app = express();
app.use(cors());
app.use(express.json());

// Routes
app.use("/api/auth", authRoutes);

const PORT = process.env.PORT || 5000;

// Initialize database and start server
(async () => {
  try {
    await sequelize.authenticate();
    console.log("Database connection established");
    
    await sequelize.sync({ alter: true });
    console.log("Database models synchronized");
    
    app.listen(PORT, () => {
      console.log(`User service running on port ${PORT}`);
    });
  } catch (error) {
    console.error("Unable to connect to database:", error);
    process.exit(1);
  }
})();
