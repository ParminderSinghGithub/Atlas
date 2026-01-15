import api from './api';

export interface Product {
  id: string;
  name: string;
  price: number | string;  // Backend returns as string
  description?: string;
  category_id?: string;
  category_name?: string;
  seller_id?: string;
  created_at?: string;
  image_url?: string;
  thumbnail_url?: string;
}

export interface Category {
  id: string;
  name: string;
  parent_id?: string;
}

export interface PaginatedResponse<T> {
  products: T[];  // API returns 'products' not 'items'
  pagination: {
    next_cursor: string | null;
    has_more: boolean;
    limit: number;
  };
}

class CatalogService {
  async getProducts(params?: {
    cursor?: string;
    limit?: number;
    category_id?: string;
  }): Promise<PaginatedResponse<Product>> {
    const response = await api.get('/v1/catalog/products', { params });
    // Return actual API response structure
    return response.data;
  }

  async getProduct(id: string): Promise<Product> {
    const response = await api.get(`/v1/catalog/products/${id}`);
    return response.data;
  }

  async getCategories(): Promise<Category[]> {
    const response = await api.get('/v1/catalog/categories');
    // API returns { categories: [...] }, not just array
    return response.data.categories || [];
  }
}

export const catalogService = new CatalogService();
