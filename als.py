# -*- coding: utf-8 -*-
"""ALS.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1hswwwLXNb1cFlJbcS_VmLLSzU41smUYb
"""

!pip install implicit
!pip install lightfm
!pip install tensorflow
!pip install pyspark

import pandas as pd
import numpy as np
from sklearn.metrics import mean_squared_error, mean_absolute_error
from sklearn.model_selection import KFold
from pyspark.sql import SparkSession
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml.recommendation import ALS as PySparkALS
from implicit.bpr import BayesianPersonalizedRanking
from scipy.sparse import csr_matrix
from sklearn.preprocessing import LabelEncoder
import warnings
import sys
from pyspark.ml.tuning import CrossValidator
from pyspark.ml.evaluation import RegressionEvaluator

from google.colab import drive
drive.mount('/content/drive')
import pandas as pd

# Definē failu ceļus
ratings_file = '/content/drive/My Drive/ratings.dat'
movies_file = '/content/drive/My Drive/movies.dat'
users_file = '/content/drive/My Drive/users.dat'
# Ielādē 'ratings.dat'
df_ratings = pd.read_csv(
    ratings_file,
    sep='::',
    engine='python',
    names=['UserID', 'MovieID', 'Rating', 'Timestamp'],
    dtype={'UserID': 'int32', 'MovieID': 'int32', 'Rating': 'int32', 'Timestamp': 'int64'},
     encoding='ISO-8859-1'
)
# Ielādē 'movies.dat'
df_movies = pd.read_csv(
    movies_file,
    sep='::',
    engine='python',
    names=['MovieID', 'Title', 'Genres'],
    dtype={'MovieID': 'int32', 'Title': 'str', 'Genres': 'str'},
     encoding='ISO-8859-1'
)
# Ielādē 'users.dat'
df_users = pd.read_csv(
    users_file,
    sep='::',
    engine='python',
    names=['UserID', 'Gender', 'Age', 'Occupation', 'Zip-code'],
    dtype={'UserID': 'int32', 'Gender': 'str', 'Age': 'int32', 'Occupation': 'int32', 'Zip-code': 'str'},
     encoding='ISO-8859-1'
)

# Pārbaudīt katru datu failu saturu
print("Ratings Data:")
print(df_ratings.head())
print("\nMovies Data:")
print(df_movies.head())
print("\nUsers Data:")
print(df_users.head())

# 1. Pārbaudām datu formas
print("Datu formas:")
print(f"Ratings: {df_ratings.shape}")
print(f"Movies: {df_movies.shape}")
print(f"Users: {df_users.shape}")

# 2. Pārbaudām unikālās vērtības
print("\nUnikālās vērtības:")
print(f"Unikālie lietotāji ratings datos: {df_ratings['UserID'].nunique()}")
print(f"Unikālās filmas ratings datos: {df_ratings['MovieID'].nunique()}")
print(f"Unikālās filmas movies datos: {df_movies['MovieID'].nunique()}")
print(f"Unikālie lietotāji users datos: {df_users['UserID'].nunique()}")

# 3. Pārbaudām trūkstošās vērtības
print("\nTrūkstošās vērtības:")
print(df_ratings.isnull().sum())
print(df_movies.isnull().sum())
print(df_users.isnull().sum())

# 4. Pārbaudām reitingu sadalījumu
print("\nReitingu sadalījums:")
print(df_ratings['Rating'].value_counts().sort_index())

# 5. Pārbaudām, vai visas filmas ratings datos ir arī movies datos
missing_movies = set(df_ratings['MovieID']) - set(df_movies['MovieID'])
print(f"\nFilmas ratings datos, kuru nav movies datos: {len(missing_movies)}")

# 6. Pārbaudām, vai visi lietotāji ratings datos ir arī users datos
missing_users = set(df_ratings['UserID']) - set(df_users['UserID'])
print(f"\nLietotāji ratings datos, kuru nav users datos: {len(missing_users)}")

# 7. Pārbaudām datu integritāti
print("\nDatu integritātes pārbaude:")
print(f"Min UserID ratings datos: {df_ratings['UserID'].min()}")
print(f"Max UserID ratings datos: {df_ratings['UserID'].max()}")
print(f"Min MovieID ratings datos: {df_ratings['MovieID'].min()}")
print(f"Max MovieID ratings datos: {df_ratings['MovieID'].max()}")

# 8. Pārbaudām, vai ir lietotāji bez reitingiem
users_without_ratings = set(df_users['UserID']) - set(df_ratings['UserID'])
print(f"\nLietotāji bez reitingiem: {len(users_without_ratings)}")

# 9. Pārbaudām, vai ir filmas bez reitingiem
movies_without_ratings = set(df_movies['MovieID']) - set(df_ratings['MovieID'])
print(f"\nFilmas bez reitingiem: {len(movies_without_ratings)}")

# 10. Izveidojam un pārbaudām filmu-reitingu matricu
movie_rating_matrix = df_ratings.pivot(index='MovieID', columns='UserID', values='Rating').fillna(0)
print("\nFilmu-reitingu matricas forma:")
print(movie_rating_matrix.shape)

# 11. Pārbaudām reitingu skaitu katram lietotājam
ratings_per_user = df_ratings['UserID'].value_counts()
print("\nReitingu skaita statistika katram lietotājam:")
print(ratings_per_user.describe())

# 12. Pārbaudām reitingu skaitu katrai filmai
ratings_per_movie = df_ratings['MovieID'].value_counts()
print("\nReitingu skaita statistika katrai filmai:")
print(ratings_per_movie.describe())

"""Datu integritāte:

Nav trūkstošu vērtību nevienā no datu kopām.
Visi lietotāji un filmas ratings datos ir atrodami arī attiecīgajās users un movies kopās.
Ir 177 filmas movies datu kopā, kurām nav neviena reitinga.


Nesakritības starp datu kopām:

Movies datu kopā ir 3883 filmas, bet ratings datu kopā ir tikai 3706 unikālas filmas.
MovieID ratings datos sniedzas līdz 3952, bet movies datu kopā ir tikai 3883 ieraksti.


Datu sadalījums:

Reitingu sadalījums ir nevienmērīgs, ar lielāku skaitu augstāku vērtējumu.
Reitingu skaits katram lietotājam un katrai filmai ievērojami atšķiras.
"""

def preprocess_data(ratings, movies, users, min_ratings_per_user=10, min_ratings_per_movie=10):
    print("Preprocessing data...")
    # Ensure movie IDs in ratings are valid
    valid_movie_ids = set(movies['MovieID']) & set(ratings['MovieID'])
    ratings = ratings[ratings['MovieID'].isin(valid_movie_ids)]
    movies = movies[movies['MovieID'].isin(valid_movie_ids)]

    # Filter users and movies based on minimum ratings
    user_ratings_count = ratings['UserID'].value_counts()
    movie_ratings_count = ratings['MovieID'].value_counts()
    valid_users = user_ratings_count[user_ratings_count >= min_ratings_per_user].index
    valid_movies = movie_ratings_count[movie_ratings_count >= min_ratings_per_movie].index
    ratings = ratings[(ratings['UserID'].isin(valid_users)) & (ratings['MovieID'].isin(valid_movies))]

    movies = movies[movies['MovieID'].isin(ratings['MovieID'])]
    users = users[users['UserID'].isin(ratings['UserID'])]

    print(f"After preprocessing: {len(movies)} movies, {len(users)} users, and {len(ratings)} ratings.")
    return ratings, movies, users

class PySparkALSRecommender:
    def __init__(self):
        self.model = None
        self.spark = SparkSession.builder.appName("ALSRecommender").getOrCreate()

    def fit(self, ratings):
        spark = self.spark
        ratings_spark = spark.createDataFrame(ratings[['UserID', 'MovieID', 'Rating']])

        # Split data into training and test sets
        (training, test) = ratings_spark.randomSplit([0.8, 0.2], seed=42)

        # Build ALS model with fixed parameters
        als = PySparkALS(
            userCol="UserID",
            itemCol="MovieID",
            ratingCol="Rating",
            nonnegative=True,
            implicitPrefs=False,
            coldStartStrategy="drop",
            rank=10,
            maxIter=10,
            regParam=0.1
        )

        # Create a parameter map with a single set of parameters
        paramMap = {als.rank: 10, als.maxIter: 10, als.regParam: 0.1}
        paramMaps = [paramMap]  # List with one parameter map

        # Create a regression evaluator
        evaluator = RegressionEvaluator(
            metricName="rmse",
            labelCol="Rating",
            predictionCol="prediction"
        )

        # Create cross-validator object
        crossval = CrossValidator(
            estimator=als,
            estimatorParamMaps=paramMaps,
            evaluator=evaluator,
            numFolds=5
        )

        # Train the model with cross-validation
        cvModel = crossval.fit(training)

        # Save the best model
        self.model = cvModel.bestModel

        # Save training and test data
        self.training = training
        self.test = test

    def evaluate(self):
        evaluator_rmse = RegressionEvaluator(metricName="rmse", labelCol="Rating", predictionCol="prediction")
        evaluator_mae = RegressionEvaluator(metricName="mae", labelCol="Rating", predictionCol="prediction")

        # Use test data for evaluation
        predictions = self.model.transform(self.test)
        rmse = evaluator_rmse.evaluate(predictions)
        mae = evaluator_mae.evaluate(predictions)
        return rmse, mae

    def predict(self, user_id, movie_id):
        spark = self.spark
        # Create a DataFrame for the user and movie
        data = spark.createDataFrame([(user_id, movie_id)], ["UserID", "MovieID"])
        # Make prediction
        prediction = self.model.transform(data).collect()
        if prediction:
            pred_rating = prediction[0]['prediction']
            pred_rating = max(1.0, min(5.0, pred_rating))  # Clip to rating scale
            return pred_rating
        else:
            return np.nan

    def recommend_movies(self, user_id, ratings, movies, n=5):
        # Get the list of movies the user has already rated
        user_rated_movies = set(ratings[ratings['UserID'] == user_id]['MovieID'])
        # Get the list of all movies
        all_movie_ids = set(movies['MovieID'])
        # Exclude movies the user has already rated
        movies_to_predict = list(all_movie_ids - user_rated_movies)
        # Create DataFrame for predictions
        data = self.spark.createDataFrame([(user_id, movie_id) for movie_id in movies_to_predict], ["UserID", "MovieID"])
        # Make predictions
        predictions = self.model.transform(data).filter("prediction IS NOT NULL").collect()
        # Sort predictions by predicted rating in descending order
        top_predictions = sorted(predictions, key=lambda x: x['prediction'], reverse=True)[:n]
        # Retrieve movie details for the top predictions
        recommended_movies = []
        for row in top_predictions:
            movie_id = row['MovieID']
            predicted_rating = max(1.0, min(5.0, row['prediction']))
            movie_info = movies[movies['MovieID'] == movie_id].iloc[0]
            recommended_movies.append({
                'MovieID': movie_id,
                'Title': movie_info['Title'],
                'Genres': movie_info['Genres'],
                'Predicted Rating': predicted_rating
            })
        return recommended_movies

def main():
    print("Sākam galveno funkciju...")
    try:
        # Ielādē datus (pieņemot, ka df_ratings, df_movies, un df_users jau ir definēti)
        ratings, movies, users = preprocess_data(df_ratings, df_movies, df_users)

        print("Datu priekšapstrāde pabeigta. Sākam modeļu apmācību...")

        # Initialize model
        als_recommender = PySparkALSRecommender()

        print(f"\nEvaluating PySparkALS model with cross-validation...")
        als_recommender.fit(ratings)

        rmse, mae = als_recommender.evaluate()
        print(f"PySparkALS model evaluation:")
        print(f"RMSE: {rmse:.4f}")
        print(f"MAE: {mae:.4f}")

        # Get recommendations for a specific user
        user_id = ratings['UserID'].min()  # Choose the first user as an example
        print(f"\nTop 5 movie recommendations for User {user_id} using PySpark ALS:")
        recommendations = als_recommender.recommend_movies(user_id, ratings, movies, n=5)
        for movie in recommendations:
            print(f"Title: {movie['Title']}, Predicted Rating: {movie['Predicted Rating']:.2f}")

        print("\nData processing and modeling completed successfully.")

        # Stop Spark session
        als_recommender.spark.stop()

    except Exception as e:
        print(f"Error in main function: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()