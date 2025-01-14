# -*- coding: utf-8 -*-
"""Hybrid_ISTAIS.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1XW4kq_n4DIhbKWJ5zD8tEkhBzk5pXrIj
"""

!pip install surprise
!pip install scikit-surprise
!pip install xgboost
!pip install catboost
!pip install lightgbm
!pip install pandas
!pip install numpy
!pip install tmdbsimple
!pip install scikit-learn

!pip install dask

!pip install aiohttp

import pandas as pd
import numpy as np
import re
import time
import requests
from tqdm import tqdm
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler
from concurrent.futures import ThreadPoolExecutor
import matplotlib.pyplot as plt
import seaborn as sns
import joblib
import os
import unicodedata

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

def word_to_number(word):
    word_dict = {
        'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
        'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
        'eleven': '11', 'twelve': '12', 'thirteen': '13', 'fourteen': '14',
        'fifteen': '15', 'sixteen': '16', 'seventeen': '17', 'eighteen': '18',
        'nineteen': '19', 'twenty': '20'
    }
    return word_dict.get(word.lower(), word)

def roman_to_arabic(roman):
    roman = roman.upper()
    roman_dict = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    result = 0
    for i, c in enumerate(roman):
        if i > 0 and roman_dict[c] > roman_dict[roman[i - 1]]:
            result += roman_dict[c] - 2 * roman_dict[roman[i - 1]]
        else:
            result += roman_dict[c]
    return str(result)

def normalize_title(title):
    import unicodedata
    return unicodedata.normalize('NFKD', title).encode('ASCII', 'ignore').decode('ASCII').lower()

def clean_title(title):
    title = re.sub(r'\s*\(\d{4}\)$', '', title)
    original_title = title
    title = normalize_title(title)
    title = re.sub(
        r'^(.*?),\s*(the|a|an|le|la|les|l\')$',
        r'\2 \1',
        title,
        flags=re.IGNORECASE
    )
    title = ' '.join(title.replace(',', '').split())
    words = title.split()
    words = [word_to_number(word) for word in words]
    title = ' '.join(words)
    title = re.sub(
        r'\b([ivxlcdm]+)\b',
        lambda m: roman_to_arabic(m.group(1)),
        title,
        flags=re.IGNORECASE
    )
    title = re.sub(r'[^\w\s\':()&]', ' ', title)
    title = ' '.join(title.split())
    return [title, original_title]

def generate_title_variants(title, original_title):
    variants = [title, original_title]
    articles = ['the', 'a', 'an', 'le', 'la', 'les', "l'"]
    words = title.lower().split()
    if words[-1] in articles:
        base_title = ' '.join(words[:-1])
        variants.extend([
            words[-1].capitalize() + ' ' + base_title,
            base_title
        ])
    elif words[0] in articles:
        base_title = ' '.join(words[1:])
        variants.extend([
            base_title,
            words[0].capitalize() + ' ' + base_title
        ])
    else:
        for article in articles:
            variants.append(f"{article.capitalize()} {title}")
            variants.append(f"{article} {title}")

    if '&' in title or ' and ' in title:
        title_with_and = title.replace('&', 'and')
        title_with_amp = title.replace(' and ', ' & ')
        variants.extend([title_with_and, title_with_amp])

    if "'" in title:
        variants.append(title.replace("'", ""))
        variants.append(title.replace("'s", "s"))

    variants.append(re.sub(r'[^\w\s]', '', title))

    if len(words) > 4:
        variants.append(' '.join(words[:4]))

    if ',' in original_title:
        parts = [part.strip() for part in original_title.split(',')]
        if len(parts) == 2:
            rearranged_title = f"{parts[1]} {parts[0]}"
            rearranged_title = normalize_title(rearranged_title)
            variants.append(rearranged_title)

    title_no_parentheses = re.sub(r'\(.*?\)', '', title).strip()
    if title_no_parentheses != title:
        variants.append(title_no_parentheses)

    variants.append(original_title)

    return list(set(variants))

def extract_year(title):
    match = re.search(r'\((\d{4})\)$', title)
    return match.group(1) if match else ''

def fetch_omdb_data(df_movies, api_key, max_retries=3):
    print("Fetching additional movie features from OMDb...")
    omdb_features = []
    failed_fetches = 0

    for idx, row in tqdm(df_movies.iterrows(), total=len(df_movies), desc="Fetching movie data"):
        original_title = row['Title']
        year = extract_year(original_title)
        cleaned_title, original_title = clean_title(original_title)

        title_variants = generate_title_variants(cleaned_title, original_title)

        success = False

        # First attempt: Try fetching with the year parameter
        for attempt in range(max_retries):
            for title in title_variants:
                params = {
                    't': title,
                    'y': year,
                    'apikey': api_key
                }
                try:
                    response = requests.get('http://www.omdbapi.com/', params=params)
                    response.raise_for_status()
                    data = response.json()
                    if data.get('Response') == 'True':
                        omdb_features.append({
                            'MovieID': row['MovieID'],
                            'Title': original_title,
                            'Actors': data.get('Actors', 'Unknown'),
                            'Director': data.get('Director', 'Unknown'),
                            'Plot': data.get('Plot', 'No Plot Available'),
                            'Genre_omdb': data.get('Genre', 'Unknown'),
                            'imdbRating': data.get('imdbRating', '0'),
                            'Runtime': data.get('Runtime', '0 min').split()[0],
                            'Year': data.get('Year', str(year) if year else 'Unknown')
                        })
                        success = True
                        break
                except requests.RequestException as e:
                    print(f"Error fetching data for movie {title} with year: {str(e)}")
            if success:
                break

        # Second attempt: Retry without the 'year' parameter if the first attempt failed
        if not success:
            for attempt in range(max_retries):
                for title in title_variants:
                    params = {
                        't': title,
                        'apikey': api_key
                    }
                    try:
                        response = requests.get('http://www.omdbapi.com/', params=params)
                        response.raise_for_status()
                        data = response.json()
                        if data.get('Response') == 'True':
                            omdb_features.append({
                                'MovieID': row['MovieID'],
                                'Title': original_title,
                                'Actors': data.get('Actors', 'Unknown'),
                                'Director': data.get('Director', 'Unknown'),
                                'Plot': data.get('Plot', 'No Plot Available'),
                                'Genre_omdb': data.get('Genre', 'Unknown'),
                                'imdbRating': data.get('imdbRating', '0'),
                                'Runtime': data.get('Runtime', '0 min').split()[0],
                                'Year': data.get('Year', 'Unknown')
                            })
                            success = True
                            break
                    except requests.RequestException as e:
                        print(f"Error fetching data for movie {title} without year: {str(e)}")
                if success:
                    break

        if not success:
            failed_fetches += 1
            print(f"Failed to fetch data for movie: {original_title}. Tried variants: {title_variants}")

    print(f"Failed to fetch data for {failed_fetches} movies.")

    df_omdb = pd.DataFrame(omdb_features)
    df_omdb['imdbRating'] = pd.to_numeric(df_omdb['imdbRating'], errors='coerce')
    df_omdb['Runtime'] = pd.to_numeric(df_omdb['Runtime'], errors='coerce')
    df_omdb['Year'] = pd.to_numeric(df_omdb['Year'], errors='coerce')

    print("OMDb data fetching completed.")
    print("NaN values in df_omdb:")
    print(df_omdb.isnull().sum())

    print("Shape of df_movies before merge:", df_movies.shape)
    print("Shape of df_omdb before merge:", df_omdb.shape)

    # Check for mismatched MovieIDs
    print("MovieIDs in df_movies but not in df_omdb:", set(df_movies['MovieID']) - set(df_omdb['MovieID']))
    print("MovieIDs in df_omdb but not in df_movies:", set(df_omdb['MovieID']) - set(df_movies['MovieID']))

    # Merge the dataframes using only MovieID
    merged_df = df_movies.merge(df_omdb, on='MovieID', how='left', suffixes=('', '_omdb'))

    print("Shape of merged_df after merge:", merged_df.shape)
    print("NaN values in merged_df after merge:")
    print(merged_df.isnull().sum())

    # Check for rows where OMDb data is missing
    missing_omdb_data = merged_df[merged_df['Actors'].isnull()]
    print(f"Number of rows with missing OMDb data: {len(missing_omdb_data)}")

    # If there are still issues, try to identify problematic rows
    if len(missing_omdb_data) > 0:
        print("Sample of rows with missing OMDb data:")
        print(missing_omdb_data[['MovieID', 'Title', 'Title_omdb']].head())

    return merged_df

def preprocess_data(ratings, movies, users, min_ratings_per_user=10, min_ratings_per_movie=10):
    print("Preprocessing data...")
    valid_movie_ids = set(movies['MovieID']) & set(ratings['MovieID'])
    ratings = ratings[ratings['MovieID'].isin(valid_movie_ids)]
    movies = movies[movies['MovieID'].isin(valid_movie_ids)]

    user_ratings_count = ratings['UserID'].value_counts()
    movie_ratings_count = ratings['MovieID'].value_counts()
    valid_users = user_ratings_count[user_ratings_count >= min_ratings_per_user].index
    valid_movies = movie_ratings_count[movie_ratings_count >= min_ratings_per_movie].index
    ratings = ratings[(ratings['UserID'].isin(valid_users)) & (ratings['MovieID'].isin(valid_movies))]

    movies = movies[movies['MovieID'].isin(ratings['MovieID'])]
    users = users[users['UserID'].isin(ratings['UserID'])]

    print(f"After preprocessing: {len(movies)} movies, {len(users)} users, and {len(ratings)} ratings.")

    print("NaN values after preprocessing:")
    print("Ratings:", ratings.isnull().sum())
    print("Movies:", movies.isnull().sum())
    print("Users:", users.isnull().sum())

    return ratings, movies, users

class ContentBasedRecommender:
    def __init__(self):
        self.tfidf = TfidfVectorizer(stop_words='english')
        self.movie_features = None
        self.movie_ids = None
        self.item_item_cf = None
        self.user_profiles = {}
        self.scaler = StandardScaler()

    def fit(self, movies_with_omdb, ratings, item_item_cf):
        print("Training Content-Based model...")
        self.item_item_cf = item_item_cf
        merged_data = movies_with_omdb

        merged_data['text_features'] = (
            merged_data['Title'] + ' ' +
            merged_data['Genres'] + ' ' +
            merged_data['Genre_omdb'].fillna('') + ' ' +
            merged_data['Actors'].fillna('') + ' ' +
            merged_data['Director'].fillna('') + ' ' +
            merged_data['Plot'].fillna('')
        )

        tfidf_matrix = self.tfidf.fit_transform(merged_data['text_features'])

        numeric_features = merged_data[['Runtime', 'imdbRating']].copy()

        for col in numeric_features.columns:
            numeric_features[col] = pd.to_numeric(numeric_features[col], errors='coerce')
            if numeric_features[col].isnull().all():
                print(f"Warning: All values in {col} are NaN. Filling with 0.")
                numeric_features[col].fillna(0, inplace=True)
            else:
                numeric_features[col].fillna(numeric_features[col].mean(), inplace=True)

        print("Numeric features after processing:")
        print(numeric_features.describe())
        print("NaN values in numeric_features:", numeric_features.isnull().sum())

        normalized_numeric_features = self.scaler.fit_transform(numeric_features)

        self.movie_features = np.hstack((tfidf_matrix.toarray(), normalized_numeric_features))
        self.movie_ids = merged_data['MovieID'].values

        # Create user profiles
        for user_id in ratings['UserID'].unique():
            user_ratings = ratings[ratings['UserID'] == user_id]
            user_profile = np.zeros(self.movie_features.shape[1])
            for _, row in user_ratings.iterrows():
                movie_idx = np.where(self.movie_ids == row['MovieID'])[0]
                if len(movie_idx) > 0:
                    user_profile += self.movie_features[movie_idx[0]] * (row['Rating'] - 2.5) / 2.5
            self.user_profiles[user_id] = user_profile

        print("Content-Based model training completed.")

    def predict(self, user_id, movie_id):
        if movie_id not in self.movie_ids:
            print(f"Movie ID {movie_id} not found in Content-Based model. Using fallback prediction.")
            return self.item_item_cf.get_fallback_prediction(user_id, movie_id)

        movie_index = np.where(self.movie_ids == movie_id)[0][0]
        movie_vector = self.movie_features[movie_index].reshape(1, -1)

        if user_id in self.user_profiles:
            user_profile = self.user_profiles[user_id].reshape(1, -1)
            similarity = cosine_similarity(user_profile, movie_vector)[0][0]
            prediction = 2.5 + 2.5 * similarity
        else:
            similarities = cosine_similarity(movie_vector, self.movie_features)[0]
            similar_indices = similarities.argsort()[::-1][1:21]
            similar_movies = self.movie_ids[similar_indices]
            prediction = np.mean([self.item_item_cf.item_means.get(movie, self.item_item_cf.global_mean) for movie in similar_movies])

        if np.isnan(prediction):
            print(f"Warning: NaN prediction for user {user_id} and movie {movie_id} in Content-Based model. Using fallback prediction.")
            return self.item_item_cf.get_fallback_prediction(user_id, movie_id)

        return min(max(prediction, 1), 5)

class HybridRecommender:
    def __init__(self, k=20, meta_model='rf'):
        self.item_item_cf = ItemItemCF(k)
        self.content_based = ContentBasedRecommender()
        if meta_model == 'rf':
            self.meta_model = RandomForestRegressor(n_estimators=100, random_state=42)
        elif meta_model == 'xgb':
            self.meta_model = XGBRegressor(n_estimators=100, random_state=42)
        else:
            raise ValueError("Unsupported meta model. Choose 'rf' or 'xgb'.")

    def fit(self, ratings, movies, users):
        print(f"Training Hybrid Recommender System with {type(self.meta_model).__name__}...")

        train_data, val_data = train_test_split(ratings, test_size=0.2, random_state=42)

        self.item_item_cf.fit(train_data)
        self.content_based.fit(movies, train_data, self.item_item_cf)
        self.users = users

        X_meta = []
        y_meta = []

        for _, row in val_data.iterrows():
            user_id, movie_id, true_rating = row['UserID'], row['MovieID'], row['Rating']

            try:
                item_item_pred = self.item_item_cf.predict(user_id, movie_id)
                content_based_pred = self.content_based.predict(user_id, movie_id)

                user_mean = train_data[train_data['UserID'] == user_id]['Rating'].mean()
                movie_mean = train_data[train_data['MovieID'] == movie_id]['Rating'].mean()
                user_age = users[users['UserID'] == user_id]['Age'].values[0]
                user_gender = users[users['UserID'] == user_id]['Gender'].values[0]

                if not np.isnan(item_item_pred) and not np.isnan(content_based_pred) and not np.isnan(user_mean) and not np.isnan(movie_mean):
                    X_meta.append([item_item_pred, content_based_pred, user_mean, movie_mean, user_age, user_gender == 'M'])
                    y_meta.append(true_rating)
                else:
                    print(f"Warning: NaN value detected for UserID={user_id}, MovieID={movie_id}")
                    print(f"item_item_pred={item_item_pred}, content_based_pred={content_based_pred}, user_mean={user_mean}, movie_mean={movie_mean}")
            except Exception as e:
                print(f"Error predicting rating: UserID={user_id}, MovieID={movie_id}, Error={str(e)}")

        print(f"Meta model training data size: {len(X_meta)}")
        if len(X_meta) > 0:
            self.meta_model.fit(X_meta, y_meta)
        else:
            print("Error: No valid data to train the meta-model.")

    def predict(self, user_id, movie_id):
        try:
            item_item_pred = self.item_item_cf.predict(user_id, movie_id)
            content_based_pred = self.content_based.predict(user_id, movie_id)

            user_mean = self.item_item_cf.user_means.get(user_id, self.item_item_cf.global_mean)
            movie_mean = self.item_item_cf.item_means.get(movie_id, self.item_item_cf.global_mean)
            user_age = self.users[self.users['UserID'] == user_id]['Age'].values[0]
            user_gender = self.users[self.users['UserID'] == user_id]['Gender'].values[0]

            meta_input = np.array([[item_item_pred, content_based_pred, user_mean, movie_mean, user_age, user_gender == 'M']])
            final_prediction = self.meta_model.predict(meta_input)[0]

            if np.isnan(final_prediction):
                print(f"Warning: NaN prediction for user {user_id} and movie {movie_id} in Hybrid model. Using fallback prediction.")
                return self.item_item_cf.get_fallback_prediction(user_id, movie_id)

            return min(max(final_prediction, 1), 5)
        except Exception as e:
            print(f"Error predicting rating: UserID={user_id}, MovieID={movie_id}, Error={str(e)}")
            return self.item_item_cf.get_fallback_prediction(user_id, movie_id)

    def recommend(self, user_id, n=5):
        user_ratings = self.item_item_cf.user_item_matrix.loc[user_id]
        unrated_movies = set(self.item_item_cf.item_index.keys()) - set(user_ratings[user_ratings > 0].index)

        with ThreadPoolExecutor(max_workers=min(32, len(unrated_movies))) as executor:
            predictions = list(executor.map(lambda movie_id: (movie_id, self.predict(user_id, movie_id)), unrated_movies))

        predictions.sort(key=lambda x: x[1], reverse=True)
        return pd.Series({movie_id: score for movie_id, score in predictions[:n]})

class ItemItemCF:
    def __init__(self, k=20):
        self.k = k
        self.item_similarity = None
        self.item_means = None
        self.user_means = None
        self.global_mean = None
        self.user_item_matrix = None

    def fit(self, ratings):
        print("Training ItemItemCF model...")
        self.ratings = ratings
        self.user_item_matrix = ratings.pivot(index='UserID', columns='MovieID', values='Rating').fillna(0)

        self.global_mean = ratings['Rating'].mean()
        self.user_means = ratings.groupby('UserID')['Rating'].mean()
        self.item_means = ratings.groupby('MovieID')['Rating'].mean()

        normalized_matrix = self.user_item_matrix.sub(self.user_means, axis=0)
        self.item_similarity = cosine_similarity(normalized_matrix.T)
        self.item_index = {movie: idx for idx, movie in enumerate(self.user_item_matrix.columns)}

        print("ItemItemCF model training completed.")

    def predict(self, user_id, movie_id):
        if movie_id not in self.item_index:
            return self.get_fallback_prediction(user_id, movie_id)

        movie_idx = self.item_index[movie_id]
        user_ratings = self.user_item_matrix.loc[user_id]

        if user_ratings.sum() == 0:
            return self.item_means.get(movie_id, self.global_mean)

        similar_items = []
        for rated_movie_id, rating in user_ratings[user_ratings > 0].items():
            if rated_movie_id in self.item_index:
                item_idx = self.item_index[rated_movie_id]
                similarity = self.item_similarity[movie_idx, item_idx]
                if not np.isnan(similarity) and not np.isnan(rating):
                    similar_items.append((similarity, rating, rated_movie_id))

        similar_items.sort(reverse=True, key=lambda x: x[0])
        similar_items = similar_items[:self.k]

        if not similar_items:
            return self.item_means.get(movie_id, self.global_mean)

        weighted_sum = sum(sim * (rating - self.item_means[sim_movie_id]) for sim, rating, sim_movie_id in similar_items)
        sum_similarities = sum(sim for sim, _, _ in similar_items)

        if sum_similarities == 0:
            return self.item_means.get(movie_id, self.global_mean)

        prediction = self.item_means[movie_id] + (weighted_sum / sum_similarities)
        return min(max(prediction, 1), 5)

    def get_fallback_prediction(self, user_id, movie_id):
        user_mean = self.user_means.get(user_id, self.global_mean)
        item_mean = self.item_means.get(movie_id, self.global_mean)
        return (user_mean + item_mean) / 2

def evaluate_hybrid_model(model, test_data):
    predictions = []
    true_ratings = []

    for _, row in test_data.iterrows():
        user_id, movie_id, true_rating = row['UserID'], row['MovieID'], row['Rating']
        try:
            predicted_rating = model.predict(user_id, movie_id)
            if not np.isnan(predicted_rating):
                predictions.append(predicted_rating)
                true_ratings.append(true_rating)
            else:
                print(f"Warning: NaN prediction for UserID={user_id}, MovieID={movie_id}")
        except Exception as e:
            print(f"Error predicting rating: UserID={user_id}, MovieID={movie_id}, Error={str(e)}")

    if len(predictions) > 0:
        mae = np.mean(np.abs(np.array(predictions) - np.array(true_ratings)))
        rmse = np.sqrt(np.mean((np.array(predictions) - np.array(true_ratings))**2))
        return mae, rmse
    else:
        print("No valid predictions for evaluation.")
        return None, None

# Main execution part
def main():
    import os
    if not os.path.exists('/content/drive'):
        from google.colab import drive
        drive.mount('/content/drive')

    ratings_file = '/content/drive/My Drive/ratings.dat'
    movies_file = '/content/drive/My Drive/movies.dat'
    users_file = '/content/drive/My Drive/users.dat'

    print("Loading data...")
    ratings = pd.read_csv(ratings_file, sep='::', engine='python', names=['UserID', 'MovieID', 'Rating', 'Timestamp'], dtype={'UserID': 'int32', 'MovieID': 'int32', 'Rating': 'int32', 'Timestamp': 'int64'}, encoding='ISO-8859-1')
    movies = pd.read_csv(movies_file, sep='::', engine='python', names=['MovieID', 'Title', 'Genres'], dtype={'MovieID': 'int32', 'Title': 'str', 'Genres': 'str'}, encoding='ISO-8859-1')
    users = pd.read_csv(users_file, sep='::', engine='python', names=['UserID', 'Gender', 'Age', 'Occupation', 'Zip-code'], dtype={'UserID': 'int32', 'Gender': 'str', 'Age': 'int32', 'Occupation': 'int32', 'Zip-code': 'str'}, encoding='ISO-8859-1')

    print("Data loaded. Checking for NaN values:")
    print("Ratings:", ratings.isnull().sum())
    print("Movies:", movies.isnull().sum())
    print("Users:", users.isnull().sum())

    ratings, movies, users = preprocess_data(ratings, movies, users)

    api_key = "18217156"
    movies = fetch_omdb_data(movies, api_key)

    print("Splitting data into train and test sets...")
    train_data, test_data = train_test_split(ratings, test_size=0.2, random_state=42)

    try:
        print("Initializing and training hybrid models...")
        hybrid_rf = HybridRecommender(meta_model='rf')
        hybrid_rf.fit(train_data, movies, users)

        hybrid_xgb = HybridRecommender(meta_model='xgb')
        hybrid_xgb.fit(train_data, movies, users)

        print("Evaluating hybrid models...")
        mae_rf, rmse_rf = evaluate_hybrid_model(hybrid_rf, test_data)
        if mae_rf is not None and rmse_rf is not None:
            print(f"Hybrid model with Random Forest MAE: {mae_rf:.4f}")
            print(f"Hybrid model with Random Forest RMSE: {rmse_rf:.4f}")
        else:
            print("Unable to evaluate Random Forest model due to insufficient valid predictions.")

        mae_xgb, rmse_xgb = evaluate_hybrid_model(hybrid_xgb, test_data)
        if mae_xgb is not None and rmse_xgb is not None:
            print(f"Hybrid model with XGBoost MAE: {mae_xgb:.4f}")
            print(f"Hybrid model with XGBoost RMSE: {rmse_xgb:.4f}")
        else:
            print("Unable to evaluate XGBoost model due to insufficient valid predictions.")

        print("Getting recommendations for user with ID 1 from both models...")
        recommendations_rf = hybrid_rf.recommend(1, n=5)
        print("Hybrid model with Random Forest recommendations for user with ID 1:")
        for movie_id, score in recommendations_rf.items():
            movie_title = movies[movies['MovieID'] == movie_id]['Title'].values[0]
            print(f"{movie_title}: {score:.2f}")

        recommendations_xgb = hybrid_xgb.recommend(1, n=5)
        print("\nHybrid model with XGBoost recommendations for user with ID 1:")
        for movie_id, score in recommendations_xgb.items():
            movie_title = movies[movies['MovieID'] == movie_id]['Title'].values[0]
            print(f"{movie_title}: {score:.2f}")

    except Exception as e:
        print(f"An error occurred during execution: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()