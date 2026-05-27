# Contamination Graph (Mermaid)

```mermaid
flowchart LR
  RawCSV[raw CSV files]
  RawCSV --> Normalize[normalize_columns]
  Normalize --> ExtractDate[extract_race_date]
  ExtractDate --> Sort[chronological_sort]
  Sort --> FeatureEng[feature_engineering]
  FeatureEng --> ModelInput[model training input]

  subgraph Risks
    FinalOdds[final_odds / closing_odds]
    AvgAgg[avg_finish_last5 / avg_speed_index_last5]
    GlobalStats[global min/max or median imputation]
  end

  FinalOdds -.-> FeatureEng
  AvgAgg -.-> FeatureEng
  GlobalStats -.-> FeatureEng
  GlobalStats -.-> ModelInput

  note over FeatureEng: before: used global shift/rolling and global normalization
  note over ModelInput: after fixes: per-horse groupby shift/rolling, no global normalization
```
```
