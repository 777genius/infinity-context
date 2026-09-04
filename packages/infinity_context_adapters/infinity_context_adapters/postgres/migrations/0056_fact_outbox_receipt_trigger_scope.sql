-- Keep strict-v4 fact receipt validation off unrelated runtime outbox events.
-- The protected checker is executable only by the canonical writer role.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DROP TRIGGER IF EXISTS trg_memory_outbox_benchmark_fact_receipt
    ON public.memory_outbox;
CREATE CONSTRAINT TRIGGER trg_memory_outbox_benchmark_fact_receipt
AFTER INSERT ON public.memory_outbox
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
WHEN (NEW.aggregate_type = 'fact')
EXECUTE FUNCTION public.memory_comparison_verify_benchmark_fact_outbox_receipt();
