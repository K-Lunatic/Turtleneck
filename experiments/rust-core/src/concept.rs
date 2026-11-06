use serde_json::{json, Value};

fn number(value: &Value) -> Result<f64, ()> {
    value.as_f64().filter(|value| value.is_finite() && value.abs() < 9_007_199_254_740_992.0).ok_or(())
}

fn rounded(value: f64) -> Result<i64, ()> {
    if !value.is_finite() || value.abs() >= 9_007_199_254_740_992.0 { return Err(()); }
    Ok(value.round_ties_even() as i64)
}

pub fn rank(encoded: &str) -> Result<Value, ()> {
    let input: Value = serde_json::from_str(encoded).map_err(|_| ())?;
    let rows = input["rows"].as_array().ok_or(())?;
    let limit = input["limit"].as_u64().filter(|value| (1..=50).contains(value)).ok_or(())? as usize;
    if rows.is_empty() { return Ok(json!({"concepts": [], "total": 0})); }
    let mut maximum = f64::NEG_INFINITY;
    for row in rows { maximum = maximum.max(number(&row["importanceRaw"])?); }
    if maximum == 0.0 { maximum = 1.0; }
    let mut ranked = Vec::with_capacity(rows.len());
    for (index, row) in rows.iter().enumerate() {
        let name = row["concept"].as_str().ok_or(())?;
        row["explanation"].as_str().ok_or(())?;
        row["evidence"].as_array().ok_or(())?;
        // Python evaluates every bucket before slicing, including invalid low-ranked sources.
        for source in row["sourceImportance"].as_object().ok_or(())?.values() {
            for score in source["scores"].as_array().ok_or(())? { number(score)?; }
            source["reasons"].as_array().ok_or(())?;
            source["referenceIds"].as_array().ok_or(())?;
        }
        let importance = rounded(number(&row["importanceRaw"])? / maximum * 100.0)?;
        let weakness = rounded((number(&row["weakRaw"])? / number(&row["attempts"])?.max(1.0) * 40.0).min(100.0))?;
        let priority = rounded(importance as f64 * 0.45 + weakness as f64 * 0.55)?;
        ranked.push((index, name, importance, weakness, priority));
    }
    ranked.sort_by(|a, b| b.4.cmp(&a.4).then_with(|| b.2.cmp(&a.2)).then_with(|| a.1.cmp(b.1)));
    let mut result = Vec::new();
    for (index, name, importance, weakness, priority) in ranked.into_iter().take(limit) {
        let row = &rows[index];
        let mut by_source = Vec::new();
        for (kind, source) in row["sourceImportance"].as_object().ok_or(())? {
            let scores = source["scores"].as_array().ok_or(())?;
            let mut total = 0.0;
            for score in scores { total += number(score)?; }
            by_source.push(json!({"sourceKind": kind, "score": if scores.is_empty() { 0 } else { rounded(total / scores.len() as f64)? },
                                  "reasons": source["reasons"].as_array().ok_or(())?.iter().take(3).collect::<Vec<_>>(),
                                  "referenceIds": source["referenceIds"].as_array().ok_or(())?.iter().take(10).collect::<Vec<_>>() }));
        }
        let explanation = row["explanation"].as_str().ok_or(())?;
        result.push(json!({"concept": name, "priority": priority, "importance": importance, "weakness": weakness,
                           "status": if weakness >= 40 { "우선 복습" } else if importance >= 60 { "핵심 개념" } else { "확인 권장" },
                           "learningMaterial": if explanation.is_empty() { "저장된 설명이 없어 원문 근거를 먼저 확인해 주세요." } else { explanation },
                           "importanceBySource": by_source, "evidence": row["evidence"].as_array().ok_or(())?.iter().take(5).collect::<Vec<_>>() }));
    }
    Ok(json!({"concepts": result, "total": rows.len()}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn uses_python_ties_to_even_and_rejects_nonfinite_scores() {
        assert_eq!(rounded(2.5).unwrap(), 2);
        assert_eq!(rounded(3.5).unwrap(), 4);
        assert!(rounded(f64::NAN).is_err());
    }
}
