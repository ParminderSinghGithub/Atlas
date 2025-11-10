import { BrowserRouter as Router, Routes, Route, Link } from "react-router-dom";

function Home() {
  return <h2 className="text-2xl font-bold text-center mt-10">Home Page 🏠</h2>;
}

function Products() {
  return <h2 className="text-2xl font-bold text-center mt-10">Products 🛒</h2>;
}

function App() {
  return (
    <Router>
      <nav className="flex justify-center gap-6 mt-4 text-lg font-semibold">
        <Link to="/">Home</Link>
        <Link to="/products">Products</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/products" element={<Products />} />
      </Routes>
    </Router>
  );
}

export default App;
