// Mock payload matching the planned /analyze-business response shape.
// Replace with a real fetch() once the backend exposes category_scores + competitors.
const sampleData = {
  score: 62,
  trade: "roofers",
  category_scores: {
    ai_presence: 68,
    seo_strength: 52,
    authority: 44,
    performance: 76,
  },
  gaps: [
    "Your business is not being cited in AI-generated answers",
    "Competitors have stronger authority signals",
    "Your website lacks structured data",
    "You are missing service-area relevance signals",
  ],
  competitors: [
    { name: "Competitor A", score: 78 },
    { name: "Competitor B", score: 74 },
  ],
};

export default sampleData;
