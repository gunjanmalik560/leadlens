# LeadLens v2 evaluation - gemini-3.5-flash-lite

**Execution accuracy: 48/50 (96%)**

| Difficulty | Correct | Total | Accuracy |
|---|---|---|---|
| easy | 15 | 15 | 100% |
| medium | 20 | 20 | 100% |
| hard | 13 | 15 | 87% |

Outcomes: api_error 1, correct 48, wrong 1

## Questions it got wrong

**Q38 (hard, api_error):** Show the running total of won revenue by month in 2026.

- LeadLens SQL: `-`
- Error: Connection error.

**Q46 (hard, wrong):** For each campaign, what is the won revenue divided by the campaign budget? Round to 2 decimals.

- LeadLens SQL: `SELECT 
    c.name,
    ROUND(COALESCE(SUM(CASE WHEN d.outcome = 'Won' THEN d.amount ELSE 0 END), 0.0) / c.budget, 2) AS revenue_to_budget_ratio
FROM campaigns c
LEFT JOIN leads l ON c.campaign_id = l.campaign_id
LEFT JOIN deals d ON l.lead_id = d.lead_id
GROUP BY c.campaign_id, c.name, c.budget;`
