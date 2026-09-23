
import { useState } from "react";
import "./App.css";

function App() {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function checkBackend() {
    setLoading(true);

    try {
      const response = await fetch(
        "http://127.0.0.1:8000/health"
      );

      if (!response.ok) {
        throw new Error("Backend returned an error");
      }

      const data = await response.json();

      setMessage(data.status);
    } catch {
      setMessage("Ошибка подключения к backend");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>Adaptive Learning Agent</h1>

      <p>Персональный AI-репетитор</p>

      <button onClick={checkBackend} disabled={loading}>
        {loading ? "Проверка..." : "Проверить Backend"}
      </button>

      <h2>Статус: {message || "Не проверен"}</h2>
    </main>
  );
}

export default App;
