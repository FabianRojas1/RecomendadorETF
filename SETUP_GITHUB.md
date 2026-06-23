# Configuración en GitHub Actions

## 1. Crear repositorio privado

1. Ve a https://github.com/new
2. Nombre: `recomendador-inversiones` (privado)
3. No inicialices con README

## 2. Subir el código

```bash
cd recomendador-inversiones   # tu carpeta del proyecto
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/TU_USUARIO/recomendador-inversiones.git
git push -u origin main
```

> El archivo `.env` NO se sube (está en `.gitignore`). Las credenciales van como Secrets.

## 3. Configurar Secrets

En GitHub: **Settings → Secrets and variables → Actions → New repository secret**

| Secret               | Valor                          |
|----------------------|--------------------------------|
| `TELEGRAM_BOT_TOKEN` | Tu token del bot de Telegram   |
| `TELEGRAM_CHAT_ID`   | Tu chat ID de Telegram         |
| `NEWS_API_KEY`       | Tu API key de NewsAPI.org      |

## 4. Habilitar los workflows

Ve a la pestaña **Actions** en tu repositorio y haz clic en **"I understand my workflows, go ahead and enable them"**.

## 5. Ejecutar manualmente (prueba)

En **Actions → Analisis Semanal de Inversiones → Run workflow**

Esto ejecutará el análisis de inmediato y enviará el mensaje + PDF a Telegram.

---

## Cuándo se ejecuta automáticamente

| Workflow              | Horario Bogotá          | Horario UTC      |
|-----------------------|-------------------------|------------------|
| Análisis semanal      | Domingos 19:00          | Lunes 00:00      |
| Monitor de precios    | Todos los días 08:00    | Todos los días 13:00 |

> **Nota:** GitHub Actions puede tener retrasos de hasta 15 minutos en horas pico.

---

## Estructura de archivos

```
recomendador-inversiones/
├── .github/
│   └── workflows/
│       ├── weekly_analysis.yml   ← Análisis dominical
│       └── daily_monitor.yml     ← Monitor de precios
├── src/
│   ├── __init__.py
│   ├── data_loader.py
│   ├── indicators.py             ← ACTUALIZADO (TF mixtos)
│   ├── scoring.py                ← ACTUALIZADO
│   ├── news_analyzer.py
│   ├── telegram_bot.py           ← ACTUALIZADO (señales fuertes + PDF)
│   └── pdf_generator.py          ← NUEVO
├── portfolio.csv
├── config.py
├── main.py                       ← ACTUALIZADO (--monitor mode)
├── requirements.txt              ← ACTUALIZADO (fpdf2)
└── .gitignore
```

## .gitignore recomendado

```
.env
*.db
*.sqlite
__pycache__/
*.pyc
.DS_Store
*.pdf
```
