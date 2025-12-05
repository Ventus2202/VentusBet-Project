import os
import joblib
import logging
from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)

class PredictorsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'predictors'
    ml_models = None # Store the loaded ML models here

    def ready(self):
        # Ensure models are loaded only once during startup
        if PredictorsConfig.ml_models is None:
            model_path = os.path.join(settings.BASE_DIR, 'ml_stats_models.pkl')
            if os.path.exists(model_path):
                try:
                    PredictorsConfig.ml_models = joblib.load(model_path)
                    logger.info("ML models loaded successfully into PredictorsConfig.")
                except Exception as e:
                    logger.error(f"Error loading ML models: {e}")
            else:
                logger.warning(f"ML models file not found at {model_path}. Prediction commands may fail.")
