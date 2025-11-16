package main

import (
	"fmt"
	"log"

	"github.com/gin-gonic/gin"

	"product-service/internal/db"
	"product-service/internal/models"
)

func main() {
	// Connect to database
	database, err := db.Connect()
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	fmt.Println("Database connection established")

	// Auto-migrate models
	err = database.AutoMigrate(&models.Product{})
	if err != nil {
		log.Fatalf("Failed to migrate database: %v", err)
	}
	fmt.Println("Database models synchronized")

	// Initialize Gin router
	r := gin.Default()

	// Routes
	r.GET("/api/products/ping", func(c *gin.Context) {
		c.JSON(200, gin.H{"message": "Product service alive"})
	})

	r.POST("/api/products", func(c *gin.Context) {
		var p models.Product
		if err := c.ShouldBindJSON(&p); err != nil {
			c.JSON(400, gin.H{"error": err.Error()})
			return
		}
		database.Create(&p)
		c.JSON(201, p)
	})

	r.GET("/api/products", func(c *gin.Context) {
		var products []models.Product
		database.Find(&products)
		c.JSON(200, products)
	})

	// Start server
	fmt.Println("Product service running on port 5000")
	if err := r.Run(":5000"); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}
