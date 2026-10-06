SELECT s.class_id,f.kp_id,f.difficulty,COUNT(*) n,COUNT(DISTINCT f.student_id) students,
 SUM(f.score) score_sum,SUM(f.max_score) max_sum,SUM(f.score)/SUM(f.max_score) score_rate,
 SUM(CASE WHEN f.score=f.max_score THEN 1 ELSE 0 END) correct_n
FROM first_current f JOIN students s USING(student_id) GROUP BY s.class_id,f.kp_id,f.difficulty;
