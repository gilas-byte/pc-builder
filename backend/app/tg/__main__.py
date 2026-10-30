from .run import main

try:
    code = main()
except SystemExit:
    raise
except BaseException:  # crash de verdade: código próprio pro script do cron avisar
    import traceback
    traceback.print_exc()
    code = 3
raise SystemExit(code)
