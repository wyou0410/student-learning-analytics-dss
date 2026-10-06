SELECT student_id,kp_id,difficulty,comparison_group,COUNT(*) n,COUNT(DISTINCT task_id) tasks,
 SUM(score) score_sum,SUM(max_score) max_sum,SUM(score)/SUM(max_score) score_rate,
 SUM(CASE WHEN score=max_score THEN 1 ELSE 0 END) correct_n,
 CAST(SUM(CASE WHEN score=max_score THEN 1 ELSE 0 END) AS REAL)/COUNT(*) correct_rate
FROM first_current GROUP BY student_id,kp_id,difficulty,comparison_group;
