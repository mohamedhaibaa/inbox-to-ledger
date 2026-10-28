# Step 13: the Lambda container image. AWS's official Python 3.12 Lambda base image.
FROM public.ecr.aws/lambda/python:3.12

COPY cloud/requirements-lambda.txt .
RUN pip install --no-cache-dir -r requirements-lambda.txt

# Only what the cloud pipeline needs: code, the investor register, the trained classifier.
COPY pipeline/ ${LAMBDA_TASK_ROOT}/pipeline/
COPY cloud/ ${LAMBDA_TASK_ROOT}/cloud/
COPY data/master/ ${LAMBDA_TASK_ROOT}/data/master/
COPY models/classifier.joblib ${LAMBDA_TASK_ROOT}/models/classifier.joblib

CMD ["cloud.handler.handler"]