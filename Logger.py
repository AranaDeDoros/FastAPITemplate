import logging
from logging.handlers import RotatingFileHandler


class Logger:

    @classmethod
    def getLogger(self) : 
        logger = logging.getLogger("app")
        file_handler = RotatingFileHandler("fastapi.log", maxBytes=10*1024*1024, backupCount=5)
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)
        return logger
  

class JsonFormatter(logging.Formatter):
    def format(self, record):
        import json
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        return json.dumps(log_entry)
