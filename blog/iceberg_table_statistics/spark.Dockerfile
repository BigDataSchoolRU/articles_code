# Spark 4.0.4 + Iceberg 1.10.1: runtime и aws-bundle кладутся прямо в jars
FROM apache/spark:4.0.4-scala2.13-java17-python3-ubuntu
ADD --chown=spark:spark https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-4.0_2.13/1.10.1/iceberg-spark-runtime-4.0_2.13-1.10.1.jar /opt/spark/jars/
ADD --chown=spark:spark https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/1.10.1/iceberg-aws-bundle-1.10.1.jar /opt/spark/jars/
COPY log4j2.properties /opt/spark/conf/log4j2.properties
