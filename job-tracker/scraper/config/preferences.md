# Preferencias de Filtrado de Job Postings

## Objetivo General
Implementar un sistema de filtrado inteligente de ofertas de trabajo que utilice IA antes de enviar notificaciones por correo electrónico.

## Arquitectura del Sistema

### Flujo de Procesamiento
1. **Scraping de Ofertas**: Recopilación inicial de job postings
2. **Filtrado Inteligente**: Envío a API de Claude AI para análisis y filtrado
3. **Distribución**: Envío por email únicamente de las ofertas relevantes

### Componentes Principales

#### 1. API de Filtrado (Claude Agent)
- **Responsabilidad**: Evaluar y filtrar job postings según preferencias del usuario
- **Input**: Lista de ofertas de trabajo en formato JSON
- **Output**: Ofertas filtradas que coinciden con criterios de interés
- **Criterios de Evaluación**:
  - Alineación con perfil profesional
  - Requisitos técnicos coincidentes
  - Ubicación geográfica (si aplica)
  - Nivel de experiencia requerido
  - Salario (si está disponible)
  - Tipo de contrato

#### 2. Motor de Preferencias
Definir qué hace que una oferta sea relevante:
- **Stack Tecnológico**: Lenguajes y frameworks de interés
- **Industria**: Sectores preferidos
- **Tipo de Rol**: Posiciones objetivo
- **Ubicación**: Remoto, híbrido, presencial
- **Seniority**: Nivel de experiencia buscado
- **Beneficios**: Requisitos deseables (flexible hours, remote work, etc.)

#### 3. Pipeline de Email
- Solo enviar correos con ofertas que pasaron el filtro de IA
- Incluir score de relevancia o justificación de por qué fue seleccionada

## Flujo Recomendado

```
Job Scraping → Almacenamiento Temporal → Claude API Filter → Base de Datos Filtrada → Email Sender
```

## Consideraciones Técnicas
- Cachear resultados para evitar sobre-procesamiento
- Implementar logging de decisiones de filtrado
- Permitir feedback del usuario para mejorar el modelo
- Ratelimit para respetabilidad de APIs